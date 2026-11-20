import json
import subprocess
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from cryptography.exceptions import InvalidTag

from addresses import receiving_address
from recovery import WORD_COUNTS, create_recovery, read_recovery, save_recovery, validate_phrase


def rpc(method, *args):
    command = ["bitcoin-cli", "-regtest", "-rpcconnect=127.0.0.1", "-rpcport=18443", "-rpcclienttimeout=2"]
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
        self.address.set(address)
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

    def check_network(self):
        info = json.loads(rpc("getblockchaininfo"))
        if info.get("chain") != "regtest":
            raise RuntimeError("Conecte um nó Bitcoin Core em regtest.")
        return info["blocks"]

    def refresh(self):
        try:
            height = self.check_network()
            self.status.set(f"Nó conectado · bloco {height}")
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
            self.status.set(str(error))

    def show_address(self, phrase):
        try:
            self.address.set(receiving_address(phrase))
        except ValueError as error:
            self.status.set(str(error))
            return
        self.status.set("Primeiro endereço da carteira em regtest.")

    def receive(self):
        phrase = self.unlock_phrase()
        if phrase is not None:
            self.show_address(phrase)


if __name__ == "__main__":
    WalletApp().mainloop()
