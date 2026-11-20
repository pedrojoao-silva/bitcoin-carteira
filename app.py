import json
import subprocess
import tkinter as tk
from decimal import Decimal
from queue import Empty, Queue
from threading import Lock, Thread
from tkinter import messagebox, simpledialog, ttk

from cryptography.exceptions import InvalidTag

from addresses import PublicAccount, public_account
from history import read_history
from recovery import (
    RECOVERY_FILE, WORD_COUNTS, create_recovery, read_public_view, read_recovery,
    save_public_account, save_recovery, validate_phrase,
)
from sending import estimated_fee, fee_rate, parse_amount, prepare_send, validate_destination
from signing import check_acceptance, sign_send
from watching import next_wallet_address, watch_wallet

SCAN_LOCK = Lock()


def rpc(method, *args, timeout=2, wallet=None, named=False):
    command = [
        "bitcoin-cli", "-regtest", "-rpcconnect=127.0.0.1", "-rpcport=18443",
        f"-rpcclienttimeout={timeout}",
    ]
    if wallet is not None:
        command.append(f"-rpcwallet={wallet}")
    if named:
        command.append("-named")
    result = subprocess.run(
        [*command, method, *args], capture_output=True, text=True, timeout=timeout + 1
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Falha ao consultar o nó.")
    return result.stdout.strip()


def check_network():
    info = json.loads(rpc("getblockchaininfo"))
    if info.get("chain") != "regtest":
        raise RuntimeError("Conecte um nó Bitcoin Core em regtest.")
    return info["blocks"]


def scan_address(account):
    check_network()
    descriptors = account.scan_objects() if isinstance(account, PublicAccount) else [f"addr({account})"]
    with SCAN_LOCK:
        scan = json.loads(
            rpc("scantxoutset", "start", json.dumps(descriptors), timeout=30),
            parse_float=Decimal,
        )
    if not scan.get("success"):
        raise RuntimeError("O Bitcoin Core não concluiu a consulta.")
    return scan


def scan_receipts(account):
    scan = scan_address(account)
    height = scan["height"]
    receipts = [
        (
            f"{output['txid']}:{output['vout']}",
            int(output["amount"] * 100_000_000),
            height - output["height"] + 1,
        )
        for output in sorted(scan["unspents"], key=lambda output: output["height"], reverse=True)
    ]
    return height, receipts


def run_node_task(window, calculate, show):
    results = Queue()

    def worker():
        try:
            results.put(calculate())
        except (OSError, RuntimeError, ValueError, KeyError, TypeError, ArithmeticError, subprocess.TimeoutExpired) as error:
            results.put(error)

    def poll():
        if not window.winfo_exists():
            return
        try:
            result = results.get_nowait()
        except Empty:
            window.after(100, poll)
            return
        show(result)

    Thread(target=worker, daemon=True).start()
    window.after(100, poll)


class WalletApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Carteira Bitcoin")
        self.geometry("790x670")
        self.minsize(620, 560)
        panel = ttk.Frame(self, padding=24)
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text="Carteira Bitcoin", font=("TkDefaultFont", 23, "bold")).pack(anchor="w")
        ttk.Label(panel, text="Rede local de testes · regtest").pack(anchor="w", pady=(4, 20))
        ttk.Label(panel, text="Saldo confirmado · regtest").pack(anchor="w")
        self.balance = tk.StringVar(value="—")
        ttk.Label(panel, textvariable=self.balance, font=("TkDefaultFont", 28, "bold")).pack(
            anchor="w", pady=(0, 12)
        )
        phrase_controls = ttk.Frame(panel)
        phrase_controls.pack(fill="x", pady=(0, 12))
        self.word_count = tk.StringVar(value="12")
        ttk.Label(phrase_controls, text="Palavras").pack(side="left")
        ttk.Combobox(
            phrase_controls, values=WORD_COUNTS, textvariable=self.word_count,
            state="readonly", width=4,
        ).pack(side="left", padx=6)
        ttk.Button(phrase_controls, text="Gerar frase de teste", command=self.create_phrase).pack(
            side="left", padx=4
        )
        ttk.Button(phrase_controls, text="Ver frase salva", command=self.show_saved_phrase).pack(
            side="left"
        )
        ttk.Button(
            panel, text="Restaurar com palavras", command=self.restore_wallet
        ).pack(anchor="w")
        ttk.Button(panel, text="Verificar nó regtest", command=self.refresh).pack(anchor="w", pady=8)
        ttk.Separator(panel).pack(fill="x", pady=12)
        receive_controls = ttk.Frame(panel)
        receive_controls.pack(fill="x")
        ttk.Button(receive_controls, text="Mostrar endereço de recebimento", command=self.receive).pack(side="left")
        self.new_address_button = ttk.Button(
            receive_controls, text="Novo endereço", command=self.rotate_address, state="disabled"
        )
        self.new_address_button.pack(side="left", padx=8)
        self.account = None
        self.rotating_address = False
        self.address = tk.StringVar()
        ttk.Entry(panel, textvariable=self.address, state="readonly").pack(fill="x", pady=8)
        self.scan_button = ttk.Button(
            panel, text="Consultar saldo confirmado", command=self.refresh_receipts,
            state="disabled",
        )
        self.scan_button.pack(anchor="w")
        self.send_button = ttk.Button(
            panel, text="Preparar envio de teste", command=self.open_send, state="disabled"
        )
        self.send_button.pack(anchor="w", pady=(4, 0))
        tabs = ttk.Notebook(panel)
        tabs.pack(fill="both", expand=True, pady=(8, 8))
        coins = ttk.Frame(tabs, padding=8)
        history_tab = ttk.Frame(tabs, padding=8)
        tabs.add(coins, text="Saídas disponíveis")
        tabs.add(history_tab, text="Histórico")
        self.build_history_tab(history_tab)
        ttk.Label(coins, text="Recebimentos confirmados ainda não gastos").pack(anchor="w")
        table = ttk.Frame(coins)
        table.pack(fill="both", expand=True, pady=(4, 8))
        self.receipts = ttk.Treeview(
            table, columns=("output", "amount", "confirmations"), show="headings", height=5,
        )
        self.receipts.heading("output", text="Transação: saída")
        self.receipts.heading("amount", text="Valor (sats)")
        self.receipts.heading("confirmations", text="Confirmações")
        self.receipts.column("output", width=400, minwidth=200)
        self.receipts.column("amount", width=110, anchor="e", stretch=False)
        self.receipts.column("confirmations", width=105, anchor="e", stretch=False)
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.receipts.yview)
        self.receipts.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.receipts.pack(side="left", fill="both", expand=True)
        self.status = tk.StringVar()
        ttk.Label(panel, textvariable=self.status, wraplength=550).pack(anchor="w")
        self.after_idle(self.open_public_view)
        self.after(15_000, self.poll_wallet)

    def build_history_tab(self, panel):
        self.history_status = tk.StringVar(value="Mostre o endereço para consultar o histórico.")
        ttk.Label(panel, textvariable=self.history_status, wraplength=550).pack(anchor="w")
        self.history_list = ttk.Treeview(
            panel, columns=("kind", "amount", "fee", "status", "confirmations"),
            show="headings", height=5,
        )
        columns = (
            ("kind", "Tipo", 90), ("amount", "Valor (sats)", 110),
            ("fee", "Taxa (sats)", 90), ("status", "Status", 165),
            ("confirmations", "Conf.", 55),
        )
        for column, label, width in columns:
            self.history_list.heading(column, text=label)
            self.history_list.column(column, width=width, minwidth=width, stretch=column == "status")
        table_scroll = ttk.Scrollbar(panel, command=self.history_list.yview)
        self.history_list.configure(yscrollcommand=table_scroll.set)
        details = ttk.Frame(panel)
        details.pack(side="bottom", fill="x", pady=(8, 0))
        self.history_txid = tk.StringVar()
        self.history_addresses = tk.StringVar()
        for label, variable in (("TXID", self.history_txid), ("Endereço", self.history_addresses)):
            row = ttk.Frame(details)
            row.pack(fill="x")
            ttk.Label(row, text=label, width=10).pack(side="left")
            ttk.Entry(row, textvariable=variable, state="readonly").pack(side="left", fill="x", expand=True)
        table_scroll.pack(side="right", fill="y")
        self.history_list.pack(fill="both", expand=True)
        self.history_list.bind("<<TreeviewSelect>>", self.show_history_details)
        self.history_running = False
        self.history_entries = {}

    def show_history_details(self, _event=None):
        selected = self.history_list.selection()
        entry = self.history_entries.get(selected[0]) if selected else None
        self.history_txid.set(entry.txid if entry else "")
        self.history_addresses.set(", ".join(entry.addresses) if entry else "")

    def poll_wallet(self):
        if self.address.get():
            self.refresh_receipts()
        self.after(15_000, self.poll_wallet)

    def wallet_view(self):
        return self.account or self.address.get()

    def refresh_history(self):
        wallet_view = self.wallet_view()
        if not wallet_view or self.history_running:
            return
        self.history_running = True
        self.history_status.set("Consultando o histórico no Bitcoin Core…")

        def calculate():
            check_network()
            return read_history(rpc, wallet_view)

        def show(result):
            self.history_running = False
            if wallet_view != self.wallet_view():
                self.refresh_history()
                return
            if isinstance(result, Exception):
                self.history_status.set(f"Histórico indisponível: {result}")
                return
            selected = self.history_list.selection()
            self.history_list.delete(*self.history_list.get_children())
            self.history_entries = {entry.txid: entry for entry in result}
            for entry in result:
                self.history_list.insert("", "end", iid=entry.txid, values=(
                    entry.kind, entry.amount, entry.fee if entry.fee is not None else "—",
                    entry.status, entry.confirmations,
                ))
            if selected and selected[0] in self.history_entries:
                self.history_list.selection_set(selected[0])
            self.show_history_details()
            self.history_status.set(
                "Atualizado pelo Bitcoin Core." if result else "Nenhuma transação encontrada."
            )

        run_node_task(self, calculate, show)

    def ask_password(self, prompt, parent=None):
        return simpledialog.askstring("Frase de recuperação", prompt, show="*", parent=parent or self)

    def new_password(self):
        password = self.ask_password("Crie uma senha local com pelo menos 12 caracteres.")
        if password is None:
            return
        confirmation = self.ask_password("Confirme a senha local.")
        if confirmation is None:
            return
        if confirmation != password:
            messagebox.showerror("Senha local", "As senhas são diferentes.", parent=self)
            return None
        return password

    def create_phrase(self):
        password = self.new_password()
        if password is None:
            return
        try:
            phrase = create_recovery(int(self.word_count.get()), password)
        except (OSError, ValueError) as error:
            messagebox.showerror("Frase de recuperação", str(error), parent=self)
            return
        self.show_address(phrase)
        self.display_phrase(phrase)

    def restore_wallet(self):
        phrase = simpledialog.askstring(
            "Restaurar carteira", "Digite as palavras BIP39 de teste na ordem correta.",
            show="*", parent=self,
        )
        if phrase is None:
            return
        try:
            phrase = validate_phrase(phrase)
            account = public_account(phrase)
        except ValueError as error:
            messagebox.showerror("Restaurar carteira", str(error), parent=self)
            return
        password = self.new_password()
        if password is None:
            return
        try:
            save_recovery(phrase, password)
        except (OSError, ValueError) as error:
            messagebox.showerror("Restaurar carteira", str(error), parent=self)
            return
        self.show_account(account, "Carteira de teste restaurada.")

    def unlock_phrase(self, parent=None):
        parent = parent or self
        password = self.ask_password("Digite a senha local.", parent)
        if password is None:
            return
        try:
            phrase = read_recovery(password)
        except InvalidTag:
            messagebox.showerror(
                "Frase de recuperação", "Senha incorreta ou arquivo alterado.", parent=parent
            )
            return
        except (OSError, ValueError, KeyError, TypeError):
            messagebox.showerror(
                "Frase de recuperação", "Não foi possível abrir o arquivo local.", parent=parent
            )
            return
        return phrase

    def show_saved_phrase(self):
        phrase = self.unlock_phrase()
        if phrase is not None:
            self.display_phrase(phrase)

    def display_phrase(self, phrase):
        words = phrase.split()
        rows = [
            "    ".join(f"{index + 1}. {words[index]}" for index in range(start, start + 3))
            for start in range(0, len(words), 3)
        ]
        messagebox.showinfo(
            "Frase de teste · BIP39",
            "Anote as palavras na ordem exibida. Use somente para testes.\n\n" + "\n".join(rows),
            parent=self,
        )

    def refresh(self):
        try:
            height = check_network()
            self.status.set(f"Nó conectado · bloco {height}")
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
            self.status.set(str(error))

    def show_address(self, phrase):
        try:
            account = public_account(phrase)
        except ValueError as error:
            self.status.set(str(error))
            return
        self.show_account(account, "Endereço de recebimento disponível em regtest.")

    def show_account(self, account, message):
        try:
            save_public_account(account)
        except OSError as error:
            message = f"Não foi possível salvar o acesso sem senha: {error}"
        self.set_address(account.first_address, account)
        self.status.set(message)

    def open_public_view(self):
        view = read_public_view()
        if view is not None:
            self.set_address(*view)
            if view[1] is None:
                self.status.set("Mostre o endereço e digite a senha uma vez para ativar os novos endereços.")
        elif RECOVERY_FILE.is_file():
            self.status.set("Mostre o endereço de recebimento para habilitar a consulta sem senha.")
        return view

    def set_address(self, address, account):
        previous = self.wallet_view()
        self.account = account
        self.address.set(address)
        self.new_address_button.configure(
            state="normal" if account is not None and not self.rotating_address else "disabled"
        )
        self.send_button.configure(state="normal" if account is not None else "disabled")
        if self.wallet_view() != previous:
            self.clear_receipts()
            self.scan_button.configure(state="normal")
            self.history_list.delete(*self.history_list.get_children())
            self.history_entries.clear()
            self.show_history_details()
            self.refresh_receipts()

    def rotate_address(self):
        account = self.account
        if account is None or self.rotating_address:
            return
        self.rotating_address = True
        self.new_address_button.configure(state="disabled")
        self.status.set("Obtendo um novo endereço de recebimento…")

        def calculate():
            check_network()
            wallet = watch_wallet(rpc, account)
            address, _ = next_wallet_address(rpc, wallet, 0)
            return address

        def show(result):
            self.rotating_address = False
            if self.account != account:
                self.new_address_button.configure(state="normal" if self.account else "disabled")
                return
            self.new_address_button.configure(state="normal")
            if isinstance(result, Exception):
                self.status.set(str(result))
                return
            try:
                save_public_account(account, result)
            except OSError as error:
                self.status.set(f"Não foi possível salvar o novo endereço: {error}")
                return
            self.set_address(result, account)
            self.status.set("Novo endereço de recebimento disponível.")

        run_node_task(self, calculate, show)

    def open_send(self):
        window = tk.Toplevel(self)
        window.title("Preparar envio · regtest")
        window.transient(self)
        window.grab_set()
        panel = ttk.Frame(window, padding=16)
        panel.pack(fill="both", expand=True)
        account = self.account
        ttk.Label(panel, text="Endereço de destino").pack(anchor="w")
        destination = ttk.Entry(panel, width=58)
        destination.pack(fill="x", pady=(4, 10))
        destination.focus_set()
        ttk.Label(panel, text="Valor em sats").pack(anchor="w")
        amount = ttk.Entry(panel)
        amount.pack(fill="x", pady=(4, 10))
        status = tk.StringVar()
        ttk.Label(panel, textvariable=status, wraplength=450).pack(anchor="w", pady=(8, 0))

        def set_controls(state):
            for widget in (destination, amount, estimate_button, review_button):
                widget.configure(state=state)

        def sign_and_confirm(draft):
            details = (
                f"Destino: {draft.destination}\n"
                f"Valor enviado: {draft.amount} sats\n"
                f"Troco: {draft.change} sats\n"
                f"Taxa efetiva: {draft.fee} sats\n"
                f"Total debitado: {draft.total} sats"
            )
            messagebox.showinfo("Revisão do envio · regtest", details, parent=window)
            phrase = self.unlock_phrase(window)
            if phrase is None:
                set_controls("normal")
                status.set("Envio cancelado.")
                return
            status.set("Assinando localmente e verificando a aceitação…")

            def sign():
                check_network()
                signed = sign_send(rpc, draft, phrase)
                check_acceptance(rpc, signed)
                return signed

            def confirm(result):
                if isinstance(result, Exception):
                    set_controls("normal")
                    status.set(str(result))
                    return
                accepted = messagebox.askyesno(
                    "Confirmar envio · regtest",
                    details + "\n\nTransmitir esta transação de teste agora?",
                    default=messagebox.NO, parent=window,
                )
                if not accepted:
                    set_controls("normal")
                    status.set("Envio cancelado.")
                    return
                status.set(f"Transmitindo…\n{result.txid}")
                window.protocol("WM_DELETE_WINDOW", lambda: None)

                def broadcast():
                    check_network()
                    txid = rpc("sendrawtransaction", result.raw)
                    if txid != result.txid:
                        raise RuntimeError("O nó retornou um identificador inesperado.")
                    return txid

                def show_txid(txid):
                    window.protocol("WM_DELETE_WINDOW", window.destroy)
                    if isinstance(txid, Exception):
                        status.set(f"Transmissão sem confirmação. Consulte o txid antes de reenviar.\n"
                                   f"{result.txid}\n{txid}")
                        return
                    status.set(f"Transação enviada.\n{txid}")
                    self.refresh_receipts()

                run_node_task(window, broadcast, show_txid)

            run_node_task(window, sign, confirm)

        def start(review):
            target = destination.get().strip()
            try:
                value = parse_amount(amount.get())
            except ValueError as error:
                status.set(str(error))
                return
            set_controls("disabled")
            status.set("Consultando o Bitcoin Core…")

            def calculate():
                check_network()
                if review:
                    return prepare_send(rpc, scan_address, account, target, value)
                _, script = validate_destination(rpc, account.first_address, target)
                rate = fee_rate(rpc)
                return f"Taxa estimada: {estimated_fee(rate, 1, script)} sats ({rate:f} sat/vB, uma entrada)."

            def show(result):
                if isinstance(result, (Exception, str)):
                    set_controls("normal")
                    status.set(str(result))
                    return
                sign_and_confirm(result)

            run_node_task(window, calculate, show)

        estimate_button = ttk.Button(panel, text="Estimar taxa", command=lambda: start(False))
        estimate_button.pack(anchor="w")
        review_button = ttk.Button(panel, text="Revisar envio", command=lambda: start(True))
        review_button.pack(anchor="w", pady=(4, 0))

    def clear_receipts(self):
        self.balance.set("—")
        self.receipts.delete(*self.receipts.get_children())

    def refresh_receipts(self):
        wallet_view = self.wallet_view()
        self.refresh_history()
        if self.scan_button.instate(("disabled",)):
            return
        self.scan_button.configure(state="disabled")
        if self.balance.get() == "—":
            self.status.set("Consultando o Bitcoin Core…")
        run_node_task(
            self, lambda: scan_receipts(wallet_view), lambda result: self.show_receipts(wallet_view, result)
        )

    def show_receipts(self, wallet_view, result):
        if self.wallet_view() != wallet_view:
            return
        self.scan_button.configure(state="normal")
        if isinstance(result, Exception):
            self.clear_receipts()
            self.status.set(str(result))
            return
        height, receipts = result
        self.receipts.delete(*self.receipts.get_children())
        for receipt in receipts:
            self.receipts.insert("", "end", values=receipt)
        total = sum(amount for _, amount, _ in receipts)
        formatted = f"{total:,}".replace(",", ".")
        self.balance.set(f"{formatted} sats")
        self.status.set(f"Consulta concluída no bloco {height}.")

    def receive(self):
        if self.account is not None:
            return
        view = self.open_public_view()
        if view is not None and view[1] is not None:
            return
        phrase = self.unlock_phrase()
        if phrase is not None:
            self.show_address(phrase)


if __name__ == "__main__":
    WalletApp().mainloop()
