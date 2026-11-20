import json
import subprocess
import tkinter as tk
from tkinter import ttk

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
