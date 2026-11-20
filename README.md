# Carteira Bitcoin

Protótipo desktop para Linux com Python e Tkinter. A interface cria e abre carteiras de teste BIP39 e exibe endereços SegWit em regtest.

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

A criação, a abertura e a exibição do endereço salvo funcionam sem nó.
Para verificar o nó ou consultar o saldo, inicie o Bitcoin Core com
`bitcoind -regtest -listen=0 -connect=0`.

## Criar e abrir a carteira

Na tela inicial, escolha **Criar carteira** ou **Abrir carteira existente**.
Na criação, selecione 12, 15, 18, 21 ou 24 palavras e defina uma senha local.
Anote a frase BIP39 exibida e digite as palavras na mesma ordem para concluir.
O aplicativo só grava a carteira após essa confirmação. Guarde a frase
anotada. A interface exibe as palavras somente na criação.

A senha local deriva a chave com scrypt. O aplicativo salva a frase com
AES-256-GCM em `~/.local/share/bitcoin-carteira/regtest-recovery.json`
(ou sob `XDG_DATA_HOME`, quando definido). O arquivo salvo permite abrir
a carteira existente com a senha local. Depois de abrir a carteira, o
aplicativo lembra a sessão de consulta neste computador e pede a senha
novamente para assinar cada envio.

**Sair da carteira** encerra a sessão, limpa o endereço, o saldo e o histórico
da tela e volta para a entrada. Os arquivos da carteira permanecem
disponíveis para a próxima abertura.

## Endereços

Um arquivo auxiliar local guarda a conta pública BIP84 e o endereço exibido.
O primeiro endereço P2WPKH usa o caminho `m/84'/1'/0'/0/0` e o prefixo
`bcrt1q`. O protótipo usa a passphrase BIP39 vazia.

Com o nó regtest em execução, clique em **Novo endereço** para receber
em outro endereço da mesma carteira. O saldo inclui os endereços anteriores
e os de troco. O protótipo monitora os índices de 0 a 999 em cada ramo BIP84
e só entrega novos endereços dentro dessa faixa.

## Saldo e recebimentos em regtest

Abra a carteira e clique em **Consultar saldo confirmado** para atualizar manualmente.
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

Abra a carteira e clique em **Preparar envio de teste**.
Informe outro endereço regtest e um valor de pelo menos 546 sats, o limite
conservador deste protótipo.

**Estimar taxa** usa a taxa do nó e calcula uma previsão para uma entrada
SegWit e uma saída de troco. **Revisar envio** seleciona saídas confirmadas
disponíveis, prepara a transação sem assinatura e mostra o destino, o valor,
o troco, a taxa efetiva e o total debitado. A taxa efetiva é a diferença
entre as entradas e as saídas da transação preparada. O troco vai para um
endereço separado, derivado no ramo interno da mesma carteira. Se o troco
ficar abaixo do limite de 294 sats, ele entra na taxa exibida na revisão.

Use fundos de teste maduros para revisar o envio. Uma recompensa de mineração
precisa de 100 confirmações para entrar na seleção.

Depois da revisão, digite a senha para assinar localmente. O Bitcoin Core
verifica a aceitação da transação assinada. Clique em **Sim** na janela
**Confirmar envio** para transmiti-la. A janela mostra o txid retornado
pelo nó. Se a transmissão ficar sem confirmação, consulte esse txid antes
de criar outro envio.

## Histórico e confirmação no destino

A aba **Histórico** consulta uma carteira de observação no Bitcoin Core.
Ela registra somente os descritores públicos, mantém os pagamentos que já foram
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
Em seguida transmite um envio com fundos de dois endereços, minera um bloco
e confere os saldos e a taxa. Ele restaura a frase em outro perfil, recria
a carteira de observação e confere a recuperação do histórico e do troco.
O teste exercita as funções de envio usadas pela janela. O
cancelamento pelo botão da interface continua sendo uma verificação manual.
