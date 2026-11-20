# Carteira Bitcoin

Protótipo desktop para Linux com Python e Tkinter. A interface gera e restaura carteiras de teste BIP39 e exibe o primeiro endereço SegWit em regtest.

## Executar

Instale as dependências Python em um ambiente virtual:

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
```

Abra o aplicativo na sessão gráfica:

```sh
python3 app.py
```

A geração, a restauração e a exibição do endereço funcionam sem nó.
Para verificar o nó ou consultar o saldo, inicie o Bitcoin Core com
`bitcoind -regtest -listen=0 -connect=0`.

## Frase de recuperação

Escolha 12, 15, 18, 21 ou 24 palavras e clique em **Gerar frase de teste**. A frase segue
BIP39, com a lista inglesa, e é gerada localmente. A senha local deriva a chave
com scrypt. O aplicativo salva a frase com AES-256-GCM em
`~/.local/share/bitcoin-carteira/regtest-recovery.json` (ou sob
`XDG_DATA_HOME`, quando definido). **Ver frase salva** reabre o arquivo
com a senha local. A senha do arquivo é independente da frase BIP39.

## Endereço e restauração

**Mostrar endereço de recebimento** desbloqueia o arquivo local e deriva o
primeiro endereço P2WPKH sempre pelo caminho BIP84 `m/84'/1'/0'/0/0`,
com prefixo `bcrt1q`. O protótipo usa a passphrase BIP39 vazia. A senha
local protege o arquivo e pode mudar sem alterar o endereço.

**Restaurar com palavras** aceita uma frase de teste da lista inglesa BIP39,
valida o checksum e salva a frase com uma nova senha local. Use um perfil
de dados vazio para restaurar. Uma frase salva nunca é sobrescrita. Para
experimentar a restauração sem alterar o perfil existente, abra o aplicativo
com um diretório de dados temporário:

```sh
XDG_DATA_HOME="$(mktemp -d)" python3 app.py
```

## Saldo e recebimentos em regtest

Mostre o endereço de recebimento e clique em **Consultar saldo confirmado**.
O saldo em sats aparece no topo da janela e é atualizado automaticamente
enquanto o endereço está visível.
O Bitcoin Core consulta as saídas ainda não gastas desse endereço no bloco
indicado. A tabela mostra o identificador da transação e da saída, o valor em
sats e as confirmações. O total pode incluir recompensas de mineração ainda
imaturas. Pagamentos pendentes e saídas já gastas ficam fora da consulta.

Para testar com o nó em execução, copie o endereço da tela no lugar de
`<endereço bcrt1q>` e gere um bloco:

```sh
bitcoin-cli -regtest generatetoaddress 1 '<endereço bcrt1q>'
```

Atualize o saldo. A recompensa deve aparecer na tabela com uma confirmação.

## Preparar envio em regtest

Mostre o endereço de recebimento e clique em **Preparar envio de teste**.
Informe outro endereço regtest e um valor de pelo menos 546 sats, o limite
conservador deste protótipo.

**Estimar taxa** usa a taxa do nó e calcula uma previsão para uma entrada
SegWit e uma saída de troco. **Revisar envio** seleciona saídas confirmadas
disponíveis, prepara a transação sem assinatura e mostra o destino, o valor,
o troco, a taxa efetiva e o total debitado. A taxa efetiva é a diferença
entre as entradas e as saídas da transação preparada. Nesta etapa, o troco
volta para o endereço de origem. Se o troco ficar abaixo do limite de 294
sats, ele entra na taxa exibida na revisão.

Use fundos de teste maduros para revisar o envio. Uma recompensa de mineração
precisa de 100 confirmações para entrar na seleção.

Depois da revisão, digite a senha para assinar localmente. O Bitcoin Core
verifica a aceitação da transação assinada. Clique em **Sim** na janela
**Confirmar envio** para transmiti-la. A janela mostra o txid retornado
pelo nó. Se a transmissão ficar sem confirmação, consulte esse txid antes
de criar outro envio.

## Histórico e confirmação no destino

A aba **Histórico** consulta uma carteira de observação no Bitcoin Core.
Ela registra somente o endereço público, mantém os pagamentos que já foram
gastos e acompanha a mempool e os blocos. Na primeira abertura, o nó pesquisa
os blocos anteriores para recuperar transações já realizadas. Os registros
voltam a aparecer depois de fechar e reabrir o aplicativo.

Um envio aparece como **Pendente** quando está na mempool e **Confirmado no
destino** quando entra em um bloco. Isso confirma o pagamento no endereço
informado. A aba mostra o valor, a taxa e as confirmações. Selecione a linha
para ver o endereço e o txid.

Para testar de ponta a ponta em regtest, gere 101 blocos para o endereço
de origem, envie para outro endereço regtest e mine mais um bloco. Confira
o recebimento no destino e atualize o saldo da carteira. Use **outro**
endereço para minerar esse último bloco, para que a recompensa não se some
ao saldo de origem durante a conferência.

### Teste automatizado de envio

Com `bitcoind` e `bitcoin-cli` no PATH e o ambiente virtual ativo, execute
na raiz do projeto:

```sh
PYTHONPATH=. python3 tests/regtest_send.py
```

O teste inicia um nó isolado em uma porta local temporária. Ele verifica que
a preparação, a assinatura e a consulta de aceitação deixam a mempool vazia.
Em seguida transmite outro envio, minera um bloco e confere os dois saldos
e a taxa. O teste exercita as funções de envio usadas pela janela. O
cancelamento pelo botão da interface continua sendo uma verificação manual.
