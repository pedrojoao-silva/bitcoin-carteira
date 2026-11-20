import json
import subprocess
import tkinter as tk
from decimal import Decimal
from queue import Empty, Queue
from threading import Thread
from tkinter import messagebox, simpledialog, ttk

from cryptography.exceptions import InvalidTag

from addresses import receiving_address
from recovery import WORD_COUNTS, create_recovery, read_recovery, save_recovery, validate_phrase
from sending import estimated_fee, fee_rate, parse_amount, prepare_send, validate_destination


def rpc(method, *args, timeout=2):
    command = [
        "bitcoin-cli", "-regtest", "-rpcconnect=127.0.0.1", "-rpcport=18443",
        f"-rpcclienttimeout={timeout}",
    ]
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


def scan_address(address):
    check_network()
    scan = json.loads(
        rpc("scantxoutset", "start", json.dumps([f"addr({address})"]), timeout=30),
        parse_float=Decimal,
    )
    if not scan.get("success"):
        raise RuntimeError("O Bitcoin Core não concluiu a consulta.")
    return scan


def scan_receipts(address):
    scan = scan_address(address)
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
        self.geometry("760x570")
        self.minsize(560, 480)
        panel = ttk.Frame(self, padding=24)
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text="Carteira Bitcoin", font=("TkDefaultFont", 23, "bold")).pack(anchor="w")
        ttk.Label(panel, text="Rede local de testes · regtest").pack(anchor="w", pady=(4, 20))
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
        ttk.Button(panel, text="Mostrar endereço de recebimento", command=self.receive).pack(anchor="w")
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
        self.balance = tk.StringVar(value="Saldo confirmado: —")
        ttk.Label(panel, textvariable=self.balance).pack(anchor="w", pady=8)
        ttk.Label(panel, text="Recebimentos confirmados ainda não gastos").pack(anchor="w")
        table = ttk.Frame(panel)
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
        ttk.Label(panel, textvariable=self.status, wraplength=470).pack(anchor="w")

    def ask_password(self, prompt):
        return simpledialog.askstring("Frase de recuperação", prompt, show="*", parent=self)

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
            address = receiving_address(phrase)
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
        self.set_address(address)
        self.status.set("Carteira de teste restaurada.")

    def unlock_phrase(self):
        password = self.ask_password("Digite a senha local.")
        if password is None:
            return
        try:
            phrase = read_recovery(password)
        except InvalidTag:
            messagebox.showerror(
                "Frase de recuperação", "Senha incorreta ou arquivo alterado.", parent=self
            )
            return
        except (OSError, ValueError, KeyError, TypeError):
            messagebox.showerror(
                "Frase de recuperação", "Não foi possível abrir o arquivo local.", parent=self
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
            self.set_address(receiving_address(phrase))
        except ValueError as error:
            self.status.set(str(error))
            return
        self.status.set("Primeiro endereço da carteira em regtest.")

    def set_address(self, address):
        if self.address.get() != address:
            self.address.set(address)
            self.clear_receipts()
            self.scan_button.configure(state="normal")
            self.send_button.configure(state="normal")

    def open_send(self):
        window = tk.Toplevel(self)
        window.title("Preparar envio · regtest")
        window.transient(self)
        window.grab_set()
        panel = ttk.Frame(window, padding=16)
        panel.pack(fill="both", expand=True)
        source = self.address.get()
        ttk.Label(panel, text="Endereço de destino").pack(anchor="w")
        destination = ttk.Entry(panel, width=58)
        destination.pack(fill="x", pady=(4, 10))
        destination.focus_set()
        ttk.Label(panel, text="Valor em sats").pack(anchor="w")
        amount = ttk.Entry(panel)
        amount.pack(fill="x", pady=(4, 10))
        status = tk.StringVar()
        ttk.Label(panel, textvariable=status, wraplength=450).pack(anchor="w", pady=(8, 0))

        def start(review):
            target = destination.get().strip()
            try:
                value = parse_amount(amount.get())
            except ValueError as error:
                status.set(str(error))
                return
            for widget in (destination, amount, estimate_button, review_button):
                widget.configure(state="disabled")
            status.set("Consultando o Bitcoin Core…")

            def calculate():
                check_network()
                if review:
                    return prepare_send(rpc, scan_address, source, target, value)
                _, script = validate_destination(rpc, source, target)
                rate = fee_rate(rpc)
                return f"Taxa estimada: {estimated_fee(rate, 1, script)} sats ({rate:f} sat/vB, uma entrada)."

            def show(result):
                for widget in (destination, amount, estimate_button, review_button):
                    widget.configure(state="normal")
                if isinstance(result, (Exception, str)):
                    status.set(str(result))
                    return
                status.set("Transação de teste preparada.")
                messagebox.showinfo(
                    "Revisão do envio · regtest",
                    f"Destino: {result.destination}\n"
                    f"Valor enviado: {result.amount} sats\n"
                    f"Troco: {result.change} sats\n"
                    f"Taxa efetiva: {result.fee} sats\n"
                    f"Total debitado: {result.total} sats\n\n"
                    "Transação preparada para revisão, sem assinatura.",
                    parent=window,
                )

            run_node_task(window, calculate, show)

        estimate_button = ttk.Button(panel, text="Estimar taxa", command=lambda: start(False))
        estimate_button.pack(anchor="w")
        review_button = ttk.Button(panel, text="Revisar envio", command=lambda: start(True))
        review_button.pack(anchor="w", pady=(4, 0))

    def clear_receipts(self):
        self.balance.set("Saldo confirmado: —")
        self.receipts.delete(*self.receipts.get_children())

    def refresh_receipts(self):
        address = self.address.get()
        self.clear_receipts()
        self.scan_button.configure(state="disabled")
        self.status.set("Consultando o Bitcoin Core…")
        run_node_task(self, lambda: scan_receipts(address), lambda result: self.show_receipts(address, result))

    def show_receipts(self, address, result):
        if self.address.get() != address:
            return
        self.scan_button.configure(state="normal")
        if isinstance(result, Exception):
            self.status.set(str(result))
            return
        height, receipts = result
        for receipt in receipts:
            self.receipts.insert("", "end", values=receipt)
        total = sum(amount for _, amount, _ in receipts)
        self.balance.set(f"Saldo confirmado: {total} sats")
        self.status.set(f"Consulta concluída no bloco {height}.")

    def receive(self):
        phrase = self.unlock_phrase()
        if phrase is not None:
            self.show_address(phrase)


if __name__ == "__main__":
    WalletApp().mainloop()
