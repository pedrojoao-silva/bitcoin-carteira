import argparse
import json
import subprocess
import tkinter as tk
from decimal import Decimal
from pathlib import Path
from queue import Empty, Queue
from threading import Lock, Thread
from tkinter import messagebox, simpledialog, ttk

from cryptography.exceptions import InvalidTag

from addresses import PublicAccount, public_account
from appearance import BACKGROUND, apply_theme, style_activity_table
from history import read_history
from networks import NETWORKS, REGTEST, SIGNET
from recovery import (
    WORD_COUNTS, forget_pending_txid, forget_session, generate_phrase, has_open_session, profile_path,
    read_pending_txid, read_public_view, read_recovery, remember_pending_txid,
    remember_session, save_public_account, save_recovery,
)
from sending import estimated_fee, fee_rate, parse_amount, prepare_send, validate_destination
from signing import check_acceptance, sign_send
from watching import next_wallet_address, watch_wallet

NETWORK = REGTEST
SCAN_LOCK = Lock()


class BroadcastUncertain(RuntimeError):
    pass


def broadcast_send(signed):
    check_network()
    remember_pending_txid(signed.txid, path=profile_path(NETWORK))
    try:
        txid = rpc("sendrawtransaction", signed.raw)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        raise BroadcastUncertain(str(error)) from error
    if txid != signed.txid:
        raise BroadcastUncertain("O nó retornou um identificador inesperado.")
    return txid


def rpc(method, *args, timeout=2, wallet=None, named=False):
    command = [
        "bitcoin-cli", f"-{NETWORK.name}", "-rpcconnect=127.0.0.1", f"-rpcport={NETWORK.rpc_port}",
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
    if info.get("chain") != NETWORK.name:
        raise RuntimeError(f"Conecte um nó Bitcoin Core na rede {NETWORK.name}.")
    if NETWORK == SIGNET and info.get("initialblockdownload", True):
        raise RuntimeError("Aguarde o Bitcoin Core terminar a sincronização da Signet.")
    if NETWORK == SIGNET and info.get("pruned"):
        raise RuntimeError("Use um nó Signet sem poda para consultar o histórico completo.")
    return info["blocks"]


def scan_address(account):
    check_network()
    descriptors = account.scan_objects() if isinstance(account, PublicAccount) else [f"addr({account})"]
    with SCAN_LOCK:
        scan = json.loads(
            rpc("scantxoutset", "start", json.dumps(descriptors), timeout=120 if NETWORK == SIGNET else 30),
            parse_float=Decimal,
        )
    if not scan.get("success"):
        raise RuntimeError("O Bitcoin Core não concluiu a consulta.")
    return scan


def scan_receipts(account):
    return receipt_rows(scan_address(account))


def query_balance(account, previous_tip):
    if previous_tip:
        check_network()
        if rpc("getbestblockhash") == previous_tip:
            return None
    scan = scan_address(account)
    return scan.get("bestblock"), *receipt_rows(scan)


def receipt_rows(scan):
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
        super().__init__(className=NETWORK.window_class)
        self.title(f"Carteira Bitcoin · {NETWORK.name}")
        self.geometry("1060x750")
        self.minsize(800, 600)
        apply_theme(self)
        image = tk.PhotoImage(file=Path(__file__).with_name("assets") / "logo.png")
        self.logo = image.subsample(27)
        self.iconphoto(True, image.subsample(5), self.logo)
        self.session_version = 0
        self.balance_tip = None
        self.account = None
        self.rotating_address = False
        self.address = tk.StringVar()
        self.status = tk.StringVar()
        self.pending_notice = tk.StringVar()
        self.entry_panel = self.build_entry_panel()
        self.wallet_panel = self.build_wallet_panel()
        self.show_entry()
        self.after_idle(self.resume_session)
        self.after(15_000, self.poll_wallet)

    def build_entry_panel(self):
        panel = ttk.Frame(self, padding=24)
        card = ttk.Frame(panel, padding=(36, 30), style="Card.TFrame")
        card.place(relx=0.5, rely=0.49, anchor="center")
        ttk.Label(card, image=self.logo, style="Surface.TLabel").pack(anchor="w")
        ttk.Label(card, text="Carteira Bitcoin", style="SurfaceHeading.TLabel").pack(
            anchor="w", pady=(8, 4)
        )
        ttk.Label(card, text=NETWORK.label, style="Network.TLabel").pack(anchor="w", pady=(0, 22))
        self.create_button = ttk.Button(
            card, text="Criar carteira", width=28, command=self.create_phrase, style="Primary.TButton",
        )
        self.create_button.pack(fill="x", pady=(0, 8))
        self.open_button = ttk.Button(card, text="Abrir carteira existente", command=self.open_existing)
        self.open_button.pack(fill="x")
        return panel

    def build_wallet_panel(self):
        panel = ttk.Frame(self)
        sidebar = ttk.Frame(panel, width=194, padding=(15, 18), style="Sidebar.TFrame")
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        ttk.Label(sidebar, image=self.logo, style="Sidebar.TLabel").pack(anchor="w")
        ttk.Label(sidebar, text="Carteira Bitcoin", style="Brand.TLabel").pack(anchor="w", pady=(5, 24))
        self.nav_buttons = {}
        for name, label in (
            ("overview", "Visão geral"), ("receive", "Receber"),
            ("history", "Histórico"), ("coins", "Saídas disponíveis"),
        ):
            button = ttk.Button(
                sidebar, text=label, style="Nav.TButton",
                command=lambda view=name: self.show_page(view),
            )
            button.pack(fill="x", pady=(0, 4))
            self.nav_buttons[name] = button
        ttk.Button(
            sidebar, text="Sair da carteira", command=self.sign_out, style="Nav.TButton",
        ).pack(side="bottom", fill="x")

        content = ttk.Frame(panel, padding=(24, 19, 24, 12))
        content.pack(side="left", fill="both", expand=True)
        top = ttk.Frame(content)
        top.pack(fill="x", pady=(0, 16))
        self.page_title = tk.StringVar()
        ttk.Label(top, textvariable=self.page_title, style="Title.TLabel").pack(side="left")
        ttk.Label(top, text=NETWORK.label, style="Network.TLabel").pack(side="right")
        ttk.Label(content, textvariable=self.status, wraplength=550, style="Muted.TLabel").pack(
            side="bottom", anchor="w", pady=(4, 0)
        )
        ttk.Label(content, textvariable=self.pending_notice, wraplength=550, style="Warning.TLabel").pack(
            side="bottom", anchor="w"
        )

        stack = ttk.Frame(content)
        stack.pack(fill="both", expand=True)
        stack.columnconfigure(0, weight=1)
        stack.rowconfigure(0, weight=1)
        self.pages = {}
        for name, build in (
            ("overview", self.build_overview), ("receive", self.build_receive_page),
            ("history", self.build_history_tab), ("coins", self.build_coins_page),
        ):
            page = ttk.Frame(stack)
            page.grid(row=0, column=0, sticky="nsew")
            build(page)
            self.pages[name] = page
        self.show_page("overview")
        return panel

    def show_page(self, page):
        self.pages[page].tkraise()
        for name, button in self.nav_buttons.items():
            button.configure(style="Current.Nav.TButton" if name == page else "Nav.TButton")
        self.page_title.set(self.nav_buttons[page].cget("text"))

    def build_overview(self, panel):
        hero = ttk.Frame(panel, padding=(24, 20), style="Hero.TFrame")
        hero.pack(fill="x", pady=(0, 20))
        ttk.Label(hero, text="Saldo confirmado", style="Hero.TLabel").pack(anchor="w")
        amount = ttk.Frame(hero, style="Hero.TFrame")
        amount.pack(fill="x", pady=(3, 0))
        self.balance = tk.StringVar(value="—")
        self.balance_btc = tk.StringVar()
        ttk.Label(amount, textvariable=self.balance, style="Balance.TLabel").pack(side="left")
        ttk.Label(amount, text="sats", style="Unit.TLabel").pack(side="left", padx=8, anchor="s", pady=9)
        ttk.Label(hero, textvariable=self.balance_btc, style="Hero.TLabel").pack(anchor="w")
        actions = ttk.Frame(hero, style="Hero.TFrame")
        actions.pack(fill="x", pady=(14, 0))
        self.send_button = ttk.Button(
            actions, text="Enviar", command=self.open_send, state="disabled", style="Primary.TButton",
        )
        self.send_button.pack(side="left")
        ttk.Button(actions, text="Receber", command=lambda: self.show_page("receive")).pack(side="left", padx=8)

        section = ttk.Frame(panel)
        section.pack(fill="x", pady=(0, 7))
        ttk.Label(section, text="Atividade recente", style="Heading.TLabel").pack(side="left")
        ttk.Button(section, text="Ver histórico", command=lambda: self.show_page("history")).pack(side="right")
        self.recent_status = tk.StringVar()
        ttk.Label(panel, textvariable=self.recent_status, style="Muted.TLabel").pack(anchor="w")
        self.recent_activity = self.build_activity_table(panel, compact=True)
        self.recent_activity.bind("<Double-1>", self.open_recent_entry)
        self.recent_activity.bind("<Return>", self.open_recent_entry)
        controls = ttk.Frame(panel)
        controls.pack(fill="x", pady=(9, 0))
        self.scan_button = ttk.Button(
            controls, text="Atualizar saldo", command=self.refresh_receipts, state="disabled",
        )
        self.scan_button.pack(side="left", padx=(0, 8))
        ttk.Button(controls, text="Verificar nó", command=self.refresh).pack(side="left")

    def build_receive_page(self, panel):
        card = ttk.Frame(panel, padding=(24, 20), style="Card.TFrame")
        card.pack(fill="x")
        ttk.Label(card, text="Endereço de recebimento", style="SurfaceHeading.TLabel").pack(anchor="w")
        ttk.Label(
            card, text="Compartilhe este endereço para receber nesta rede de teste.",
            style="SurfaceMuted.TLabel",
        ).pack(anchor="w", pady=(4, 14))
        ttk.Entry(card, textvariable=self.address, state="readonly", font="TkFixedFont").pack(
            fill="x", pady=(0, 12)
        )
        controls = ttk.Frame(card, style="Surface.TFrame")
        controls.pack(fill="x")
        self.copy_address_button = ttk.Button(
            controls, text="Copiar endereço", state="disabled", style="Primary.TButton",
            command=lambda: self.copy_public_text(self.address.get(), "Endereço copiado."),
        )
        self.copy_address_button.pack(side="left", padx=(0, 8))
        self.new_address_button = ttk.Button(
            controls, text="Novo endereço", command=self.rotate_address, state="disabled",
        )
        self.new_address_button.pack(side="left")

    def build_coins_page(self, panel):
        ttk.Label(
            panel, text="Recebimentos confirmados ainda não gastos", style="Muted.TLabel",
        ).pack(anchor="w", pady=(0, 8))
        table = ttk.Frame(panel)
        table.pack(fill="both", expand=True)
        self.receipts = ttk.Treeview(
            table, columns=("output", "amount", "confirmations"), show="headings", height=5,
        )
        self.receipts.heading("output", text="Transação: saída", anchor="w")
        self.receipts.heading("amount", text="Valor (sats)", anchor="e")
        self.receipts.heading("confirmations", text="Confirmações", anchor="e")
        self.receipts.column("output", width=320, minwidth=130)
        self.receipts.column("amount", width=114, anchor="e", stretch=False)
        self.receipts.column("confirmations", width=108, anchor="e", stretch=False)
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.receipts.yview)
        self.receipts.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.receipts.pack(side="left", fill="both", expand=True)
        style_activity_table(self.receipts)

    def copy_public_text(self, value, confirmation):
        if value:
            self.clipboard_clear()
            self.clipboard_append(value)
            self.status.set(confirmation)

    def show_entry(self):
        exists = profile_path(NETWORK).is_file()
        self.create_button.configure(
            state="disabled" if exists else "normal", style="TButton" if exists else "Primary.TButton",
        )
        self.open_button.configure(
            state="normal" if exists else "disabled", style="Primary.TButton" if exists else "TButton",
        )
        self.wallet_panel.pack_forget()
        self.entry_panel.pack(fill="both", expand=True)
        (self.open_button if exists else self.create_button).focus_set()

    def show_wallet(self, address, account):
        self.session_version += 1
        self.history_running = False
        self.rotating_address = False
        self.entry_panel.pack_forget()
        self.wallet_panel.pack(fill="both", expand=True)
        self.show_page("overview")
        self.set_address(address, account)
        self.show_pending_notice()

    def resume_session(self):
        if has_open_session(path=profile_path(NETWORK)):
            view = read_public_view(path=profile_path(NETWORK), network=NETWORK)
            if view is not None and view[1] is not None:
                self.show_wallet(*view)

    def open_existing(self):
        phrase = self.unlock_phrase()
        if phrase is None:
            return
        try:
            account = public_account(phrase, network=NETWORK)
        except ValueError as error:
            messagebox.showerror("Abrir carteira", str(error), parent=self)
            return
        view = read_public_view(path=profile_path(NETWORK), network=NETWORK)
        address = view[0] if view is not None and view[1] == account else account.first_address
        self.start_session(address, account)

    def start_session(self, address, account):
        try:
            save_public_account(account, address, path=profile_path(NETWORK))
            remember_session(path=profile_path(NETWORK))
        except OSError as error:
            messagebox.showerror(
                "Sessão local", f"Não foi possível lembrar a sessão neste computador.\n{error}", parent=self
            )
        self.show_wallet(address, account)

    def sign_out(self):
        try:
            forget_session(path=profile_path(NETWORK))
        except OSError as error:
            messagebox.showerror("Sair da carteira", str(error), parent=self)
            return
        self.session_version += 1
        self.account = None
        self.address.set("")
        self.clear_receipts()
        self.clear_history()
        self.show_history_details()
        self.history_status.set("Aguardando consulta do histórico.")
        self.status.set("")
        self.pending_notice.set("")
        self.show_entry()

    def show_pending_notice(self):
        txid = read_pending_txid(path=profile_path(NETWORK))
        self.pending_notice.set(
            f"Confira o envio anterior no histórico antes de reenviar.\n{txid}" if txid else ""
        )

    def mark_broadcast_known(self, txid):
        try:
            forget_pending_txid(txid, path=profile_path(NETWORK))
        except OSError as error:
            self.status.set(f"Não foi possível limpar o aviso de envio: {error}")
        self.show_pending_notice()

    def build_activity_table(self, panel, *, compact=False):
        area = ttk.Frame(panel)
        area.pack(fill="both", expand=True)
        columns = [
            ("kind", "Tipo", 82), ("amount", "Valor (sats)", 116), ("status", "Status", 164),
        ]
        if not compact:
            columns[2:2] = [("fee", "Taxa (sats)", 90)]
            columns.append(("confirmations", "Conf.", 53))
        table = ttk.Treeview(
            area, columns=[column for column, _, _ in columns],
            show="headings", height=4 if compact else 7, selectmode="browse",
        )
        for column, label, width in columns:
            anchor = "e" if column in {"amount", "fee", "confirmations"} else "w"
            table.heading(column, text=label, anchor=anchor)
            table.column(column, width=width, minwidth=width, anchor=anchor, stretch=column == "status")
        scroll = ttk.Scrollbar(area, orient="vertical", command=table.yview)
        table.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        table.pack(side="left", fill="both", expand=True)
        style_activity_table(table)
        return table

    def build_history_tab(self, panel):
        self.history_status = tk.StringVar(value="Aguardando consulta do histórico.")
        ttk.Label(
            panel, textvariable=self.history_status, wraplength=540, style="Muted.TLabel",
        ).pack(anchor="w", pady=(0, 8))
        details = ttk.Frame(panel, padding=(12, 10), style="Surface.TFrame")
        details.pack(side="bottom", fill="x", pady=(10, 0))
        self.history_txid = tk.StringVar()
        self.history_addresses = tk.StringVar()
        for label, variable in (("TXID", self.history_txid), ("Endereço", self.history_addresses)):
            row = ttk.Frame(details, style="Surface.TFrame")
            row.pack(fill="x", pady=3)
            ttk.Label(row, text=label, width=9, style="SurfaceMuted.TLabel").pack(side="left")
            ttk.Entry(row, textvariable=variable, state="readonly", font="TkFixedFont", width=24).pack(
                side="left", fill="x", expand=True
            )
            if label == "TXID":
                self.copy_txid_button = ttk.Button(
                    row, text="Copiar TXID", state="disabled",
                    command=lambda: self.copy_public_text(self.history_txid.get(), "TXID copiado."),
                )
                self.copy_txid_button.pack(side="left", padx=(8, 0))
        self.history_list = self.build_activity_table(panel)
        self.history_list.bind("<<TreeviewSelect>>", self.show_history_details)
        self.history_running = False
        self.history_entries = {}

    def open_recent_entry(self, _event):
        selected = self.recent_activity.selection()
        if selected and self.history_list.exists(selected[0]):
            self.show_page("history")
            self.history_list.selection_set(selected[0])
            self.history_list.see(selected[0])
            self.history_list.focus(selected[0])
            self.history_list.focus_set()

    def clear_history(self):
        for table in (self.history_list, self.recent_activity):
            table.delete(*table.get_children())
        self.history_entries.clear()
        self.recent_status.set("Aguardando consulta do histórico.")

    def populate_history(self, entries):
        selected = self.history_list.selection()
        recent_selected = self.recent_activity.selection()
        self.clear_history()
        self.history_entries = {entry.txid: entry for entry in entries}
        for index, entry in enumerate(entries):
            tags = ["alternate"] if index % 2 else []
            if entry.confirmations > 0 and entry.status != "Recompensa imatura":
                tags.append("confirmed")
            elif entry.status in {"Conflito", "Cancelado"}:
                tags.append("failed")
            else:
                tags.append("pending")
            self.history_list.insert(
                "", "end", iid=entry.txid, tags=tags,
                values=(entry.kind, entry.amount, entry.fee if entry.fee is not None else "—",
                        entry.status, entry.confirmations),
            )
            if index < 5:
                self.recent_activity.insert(
                    "", "end", iid=entry.txid, tags=tags, values=(entry.kind, entry.amount, entry.status),
                )
        if selected and selected[0] in self.history_entries:
            self.history_list.selection_set(selected[0])
        if recent_selected and self.recent_activity.exists(recent_selected[0]):
            self.recent_activity.selection_set(recent_selected[0])
        self.recent_status.set("" if entries else "Nenhuma transação encontrada.")
        self.show_history_details()

    def show_history_details(self, _event=None):
        selected = self.history_list.selection()
        entry = self.history_entries.get(selected[0]) if selected else None
        self.history_txid.set(entry.txid if entry else "")
        self.history_addresses.set(", ".join(entry.addresses) if entry else "")
        self.copy_txid_button.configure(state="normal" if entry else "disabled")

    def poll_wallet(self):
        if self.address.get():
            self.refresh_receipts(only_if_tip_changed=True)
        self.after(15_000, self.poll_wallet)

    def wallet_view(self):
        return self.account or self.address.get()

    def refresh_history(self):
        wallet_view = self.wallet_view()
        if not wallet_view or self.history_running:
            return
        session = self.session_version
        self.history_running = True
        self.history_status.set("Consultando o histórico no Bitcoin Core…")

        def calculate():
            check_network()
            return read_history(rpc, wallet_view)

        def show(result):
            if session != self.session_version:
                return
            self.history_running = False
            if wallet_view != self.wallet_view():
                self.refresh_history()
                return
            if isinstance(result, Exception):
                self.history_status.set(f"Histórico indisponível: {result}")
                self.recent_status.set("Histórico indisponível. Consulte o nó Bitcoin Core.")
                return
            self.populate_history(result)
            pending_txid = read_pending_txid(path=profile_path(NETWORK))
            pending_entry = self.history_entries.get(pending_txid)
            if pending_entry and (
                pending_entry.status == "Pendente" or pending_entry.confirmations > 0
            ):
                self.mark_broadcast_known(pending_txid)
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
        if len(password) < 12:
            messagebox.showerror("Senha local", "Use pelo menos 12 caracteres.", parent=self)
            return None
        if confirmation != password:
            messagebox.showerror("Senha local", "As senhas são diferentes.", parent=self)
            return None
        return password

    def create_phrase(self):
        sizes = ", ".join(map(str, WORD_COUNTS))
        count = simpledialog.askinteger(
            "Criar carteira", f"Escolha a quantidade de palavras ({sizes}).",
            initialvalue=12, parent=self,
        )
        if count is None:
            return
        if count not in WORD_COUNTS:
            messagebox.showerror("Criar carteira", f"Escolha uma destas quantidades: {sizes}.", parent=self)
            return
        password = self.new_password()
        if password is None:
            return
        phrase = generate_phrase(count)
        self.display_phrase(phrase)
        while True:
            typed = simpledialog.askstring(
                "Confirmar palavras", "Digite todas as palavras anotadas, na ordem correta.",
                show="*", parent=self,
            )
            if typed is None:
                return
            if " ".join(typed.lower().split()) == phrase:
                break
            messagebox.showerror(
                "Confirmar palavras", "As palavras não conferem. Confira a ordem e tente novamente.",
                parent=self,
            )

        try:
            account = public_account(phrase, network=NETWORK)
            save_recovery(phrase, password, path=profile_path(NETWORK), network=NETWORK)
        except (OSError, ValueError) as error:
            messagebox.showerror("Criar carteira", str(error), parent=self)
            self.show_entry()
            return
        self.start_session(account.first_address, account)

    def unlock_phrase(self, parent=None):
        parent = parent or self
        password = self.ask_password("Digite a senha local.", parent)
        if password is None:
            return
        try:
            phrase = read_recovery(password, path=profile_path(NETWORK), network=NETWORK)
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

    def set_address(self, address, account):
        previous = self.wallet_view()
        self.account = account
        self.address.set(address)
        self.copy_address_button.configure(state="normal" if address else "disabled")
        self.new_address_button.configure(
            state="normal" if account is not None and not self.rotating_address else "disabled"
        )
        self.send_button.configure(state="normal" if account is not None else "disabled")
        if self.wallet_view() != previous:
            self.clear_receipts()
            self.scan_button.configure(state="normal")
            self.clear_history()
            self.show_history_details()
            self.refresh_receipts()

    def rotate_address(self):
        account = self.account
        if account is None or self.rotating_address:
            return
        session = self.session_version
        self.rotating_address = True
        self.new_address_button.configure(state="disabled")
        self.status.set("Obtendo um novo endereço de recebimento…")

        def calculate():
            check_network()
            wallet = watch_wallet(rpc, account)
            address, _ = next_wallet_address(rpc, wallet, 0)
            return address

        def show(result):
            if session != self.session_version:
                return
            self.rotating_address = False
            if self.account != account:
                self.new_address_button.configure(state="normal" if self.account else "disabled")
                return
            self.new_address_button.configure(state="normal")
            if isinstance(result, Exception):
                self.status.set(str(result))
                return
            try:
                save_public_account(account, result, path=profile_path(NETWORK))
            except OSError as error:
                self.status.set(f"Não foi possível salvar o novo endereço: {error}")
                return
            self.set_address(result, account)
            self.status.set("Novo endereço de recebimento disponível.")

        run_node_task(self, calculate, show)

    def review_payment(self, parent, draft):
        dialog = tk.Toplevel(parent)
        dialog.title(f"Revisar envio · {NETWORK.name}")
        dialog.configure(background=BACKGROUND)
        dialog.transient(parent)
        dialog.resizable(False, False)
        panel = ttk.Frame(dialog, padding=24)
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text="Revisar envio", style="Title.TLabel").pack(anchor="w")
        ttk.Label(panel, text=NETWORK.label, style="Network.TLabel").pack(anchor="w", pady=(6, 14))
        ttk.Label(panel, text="Destino", style="Muted.TLabel").pack(anchor="w")
        target = tk.StringVar(master=dialog, value=draft.destination)
        ttk.Entry(panel, textvariable=target, state="readonly", font="TkFixedFont", width=54).pack(
            fill="x", pady=(5, 13),
        )
        card = ttk.Frame(panel, padding=(14, 10), style="Card.TFrame")
        card.pack(fill="x", pady=(0, 15))
        card.columnconfigure(1, weight=1)
        items = (
            ("Valor enviado", draft.amount), ("Troco", draft.change),
            ("Taxa efetiva", draft.fee), ("Total debitado", draft.total),
        )
        for index, (label, amount) in enumerate(items):
            strong = index == len(items) - 1
            style = "SurfaceHeading.TLabel" if strong else "Surface.TLabel"
            label_style = style if strong else "SurfaceMuted.TLabel"
            ttk.Label(card, text=label, style=label_style).grid(row=index, column=0, sticky="w", pady=3)
            formatted = f"{amount:,}".replace(",", ".")
            ttk.Label(card, text=f"{formatted} sats", style=style).grid(
                row=index, column=1, sticky="e", pady=3,
            )
        actions = ttk.Frame(panel)
        actions.pack(fill="x")
        accepted = False

        def finish(proceed):
            nonlocal accepted
            accepted = proceed
            dialog.destroy()

        ttk.Button(
            actions, text="Continuar para assinatura", style="Primary.TButton",
            command=lambda: finish(True),
        ).pack(side="right")
        back = ttk.Button(actions, text="Voltar", command=lambda: finish(False))
        back.pack(side="right", padx=(0, 8))
        dialog.protocol("WM_DELETE_WINDOW", lambda: finish(False))
        dialog.bind("<Escape>", lambda _event: finish(False))
        dialog.wait_visibility()
        dialog.grab_set()
        back.focus_set()
        parent.wait_window(dialog)
        if parent.winfo_exists():
            parent.grab_set()
        return accepted

    def open_send(self):
        pending_txid = read_pending_txid(path=profile_path(NETWORK))
        if pending_txid and not messagebox.askyesno(
            "Envio anterior sem confirmação",
            f"O nó ainda não confirmou a transmissão anterior.\n{pending_txid}\n\n"
            "Você verificou esse envio e quer preparar um novo pagamento?",
            default=messagebox.NO, parent=self,
        ):
            self.refresh_history()
            return
        window = tk.Toplevel(self)
        window.title(f"Preparar envio · {NETWORK.name}")
        window.configure(background=BACKGROUND)
        window.transient(self)
        window.grab_set()
        panel = ttk.Frame(window, padding=22)
        panel.pack(fill="both", expand=True)
        account = self.account
        ttk.Label(panel, text="Preparar envio de teste", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(panel, text=NETWORK.label, style="Muted.TLabel").pack(anchor="w", pady=(3, 15))
        ttk.Label(panel, text="Endereço de destino").pack(anchor="w")
        destination = ttk.Entry(panel, width=56, font="TkFixedFont")
        destination.pack(fill="x", pady=(4, 12))
        destination.focus_set()
        ttk.Label(panel, text="Valor em sats").pack(anchor="w")
        amount = ttk.Entry(panel, width=20)
        amount.pack(anchor="w", pady=(4, 14))
        actions = ttk.Frame(panel)
        actions.pack(fill="x")
        status = tk.StringVar()
        ttk.Label(panel, textvariable=status, wraplength=450, style="Muted.TLabel").pack(anchor="w", pady=(10, 0))

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
            if not self.review_payment(window, draft):
                set_controls("normal")
                status.set("Revise o destino e o valor antes de continuar.")
                return
            phrase = self.unlock_phrase(window)
            if phrase is None:
                set_controls("normal")
                status.set("Envio cancelado.")
                return
            status.set("Assinando localmente e verificando a aceitação…")

            def sign():
                check_network()
                signed = sign_send(rpc, draft, phrase, network=NETWORK)
                check_acceptance(rpc, signed)
                return signed

            def confirm(result):
                if isinstance(result, Exception):
                    set_controls("normal")
                    status.set(str(result))
                    return
                accepted = messagebox.askyesno(
                    f"Confirmar envio · {NETWORK.name}",
                    details + "\n\nTransmitir esta transação de teste agora?",
                    default=messagebox.NO, parent=window,
                )
                if not accepted:
                    set_controls("normal")
                    status.set("Envio cancelado.")
                    return
                status.set(f"Transmitindo…\n{result.txid}")
                window.protocol("WM_DELETE_WINDOW", lambda: None)

                def show_txid(txid):
                    window.protocol("WM_DELETE_WINDOW", window.destroy)
                    if isinstance(txid, BroadcastUncertain):
                        status.set(f"Transmissão sem confirmação. Consulte o txid antes de reenviar.\n"
                                   f"{result.txid}\n{txid}")
                        self.show_pending_notice()
                        self.refresh_history()
                        return
                    if isinstance(txid, Exception):
                        status.set(f"O envio parou antes da transmissão.\n{txid}")
                        set_controls("normal")
                        return
                    status.set(f"Transação enviada.\n{txid}")
                    self.mark_broadcast_known(txid)
                    self.refresh_receipts()

                run_node_task(window, lambda: broadcast_send(result), show_txid)

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

        estimate_button = ttk.Button(actions, text="Estimar taxa", command=lambda: start(False))
        estimate_button.pack(side="left", padx=(0, 8))
        review_button = ttk.Button(
            actions, text="Revisar envio", command=lambda: start(True), style="Primary.TButton",
        )
        review_button.pack(side="left")

    def clear_receipts(self):
        self.balance_tip = None
        self.balance.set("—")
        self.balance_btc.set("")
        self.receipts.delete(*self.receipts.get_children())

    def refresh_receipts(self, only_if_tip_changed=False):
        wallet_view = self.wallet_view()
        self.refresh_history()
        if self.scan_button.instate(("disabled",)):
            return
        self.scan_button.configure(state="disabled")
        session = self.session_version
        if self.balance.get() == "—":
            self.status.set("Consultando o Bitcoin Core…")
        previous_tip = self.balance_tip if only_if_tip_changed else None
        run_node_task(
            self, lambda: query_balance(wallet_view, previous_tip),
            lambda result: self.show_receipts(wallet_view, session, result),
        )

    def show_receipts(self, wallet_view, session, result):
        if session != self.session_version or self.wallet_view() != wallet_view:
            return
        self.scan_button.configure(state="normal")
        if isinstance(result, Exception):
            self.clear_receipts()
            self.status.set(str(result))
            return
        if result is None:
            return
        self.balance_tip, height, receipts = result
        self.receipts.delete(*self.receipts.get_children())
        for index, receipt in enumerate(receipts):
            self.receipts.insert("", "end", values=receipt, tags=("alternate",) if index % 2 else ())
        total = sum(amount for _, amount, _ in receipts)
        formatted = f"{total:,}".replace(",", ".")
        self.balance.set(formatted)
        btc = f"{Decimal(total).scaleb(-8):.8f}".replace(".", ",")
        self.balance_btc.set(f"{btc} BTC")
        self.status.set(f"Consulta concluída no bloco {height}.")

def main():
    global NETWORK
    parser = argparse.ArgumentParser(description="Carteira Bitcoin para redes de teste")
    parser.add_argument("--network", choices=NETWORKS, default=REGTEST.name)
    options = parser.parse_args()
    NETWORK = NETWORKS[options.network]
    WalletApp().mainloop()


if __name__ == "__main__":
    main()
