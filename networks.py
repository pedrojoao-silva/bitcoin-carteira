"""Networks supported by the test-only wallet."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Network:
    name: str
    label: str
    rpc_port: int
    bech32_prefix: str
    window_class: str

    @property
    def recovery_context(self):
        return f"bitcoin-carteira:{self.name}:recovery:v1".encode("ascii")


REGTEST = Network("regtest", "Rede local de testes · regtest", 18443, "bcrt", "BitcoinCarteira")
SIGNET = Network("signet", "Rede pública de testes · Signet", 38332, "tb", "BitcoinCarteiraSignet")
NETWORKS = {network.name: network for network in (REGTEST, SIGNET)}
