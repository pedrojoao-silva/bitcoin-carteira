import json
import subprocess
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from cryptography.exceptions import InvalidTag

from recovery import create_recovery, read_recovery

WALLET = "carteira-lab"


def rpc(method, *args, wallet=False):
    command = ["bitcoin-cli", "-regtest", "-rpcconnect=127.0.0.1", "-rpcport=18443", "-rpcclienttimeout=2"]
    if wallet:
        command.append(f"-rpcwallet={WALLET}")
    result = subprocess.run(
        [*command, method, *args], capture_output=True, text=True, timeout=3
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Falha ao consultar o nó.")
    return result.stdout.strip()


class WalletApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Carteira Bitcoin")
        self.geometry("640x420")
        self.minsize(520, 340)
        panel = ttk.Frame(self, padding=24)
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text="Carteira Bitcoin", font=("TkDefaultFont", 23, "bold")).pack(anchor="w")
        ttk.Label(panel, text="Rede local de testes · regtest").pack(anchor="w", pady=(4, 20))
        phrase_controls = ttk.Frame(panel)
        phrase_controls.pack(fill="x", pady=(0, 12))
        self.word_count = tk.StringVar(value="12")
        ttk.Label(phrase_controls, text="Palavras").pack(side="left")
        ttk.Combobox(
            phrase_controls, values=("12", "24"), textvariable=self.word_count,
            state="readonly", width=4,
        ).pack(side="left", padx=6)
        ttk.Button(phrase_controls, text="Gerar frase de teste", command=self.create_phrase).pack(
            side="left", padx=4
        )
        ttk.Button(phrase_controls, text="Ver frase salva", command=self.show_saved_phrase).pack(
            side="left"
        )
        self.balance = tk.StringVar(value="Saldo indisponível")
        ttk.Label(panel, textvariable=self.balance, font=("TkDefaultFont", 16)).pack(anchor="w")
        ttk.Button(panel, text="Atualizar saldo", command=self.refresh).pack(anchor="w", pady=8)
        ttk.Separator(panel).pack(fill="x", pady=12)
        ttk.Button(panel, text="Gerar endereço de teste", command=self.receive).pack(anchor="w")
        self.address = tk.StringVar()
        ttk.Entry(panel, textvariable=self.address, state="readonly").pack(fill="x", pady=8)
        self.status = tk.StringVar()
        ttk.Label(panel, textvariable=self.status, wraplength=470).pack(anchor="w")
        self.after_idle(self.refresh)

    def ask_password(self, prompt):
        return simpledialog.askstring("Frase de recuperação", prompt, show="*", parent=self)

    def create_phrase(self):
        password = self.ask_password("Crie uma senha local com pelo menos 12 caracteres.")
        if password is None:
            return
        confirmation = self.ask_password("Confirme a senha local.")
        if confirmation is None:
            return
        if confirmation != password:
            messagebox.showerror("Senha local", "As senhas são diferentes.", parent=self)
            return
        try:
            phrase = create_recovery(int(self.word_count.get()), password)
        except (OSError, ValueError) as error:
            messagebox.showerror("Frase de recuperação", str(error), parent=self)
            return
        self.display_phrase(phrase)

    def show_saved_phrase(self):
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

    def check_network(self):
        info = json.loads(rpc("getblockchaininfo"))
        if info.get("chain") != "regtest":
            raise RuntimeError("Conecte um nó Bitcoin Core em regtest.")
        return info["blocks"]

    def refresh(self):
        try:
            height = self.check_network()
            amount = rpc("getbalance", wallet=True)
            self.balance.set(f"{amount} BTC de teste")
            self.status.set(f"Nó conectado · bloco {height}")
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
            self.balance.set("Saldo indisponível")
            self.status.set(str(error))

    def receive(self):
        try:
            self.check_network()
            self.address.set(rpc("getnewaddress", wallet=True))
            self.status.set("Endereço de teste gerado.")
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
            self.status.set(str(error))


if __name__ == "__main__":
    WalletApp().mainloop()
