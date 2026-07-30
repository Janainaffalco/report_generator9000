# Deploy no Coolify

Este projeto deve ser publicado como **uma Application com build pack
Dockerfile**. Não use Nixpacks, Static ou `compose.dev.yaml`: o `Dockerfile` de
produção já compila o React, instala o backend Python e inclui o Chromium usado
nas capturas.

## O que a demo entrega hoje

- upload da planilha de controle;
- seleção de um atendimento elegível;
- geração assíncrona, sem interação durante o pipeline;
- download do relatório em `.docx`.

Esta versão ainda **não oferece prévia renderizada nem download em PDF**. Para a
demo, apresente o `.docx` gerado e abra-o no Word após o download.

## Pré-requisitos

- uma VPS com Coolify e pelo menos 2 vCPU, 4 GB de RAM e espaço livre para a
  imagem Playwright/Chromium;
- acesso do Coolify ao repositório
  `seriouslyvictor/report_generator9000`;
- uma chave válida do Gemini;
- opcionalmente, os Gated Drop Folders dos atendimentos que serão demonstrados.

O Master aprovado e client-neutral é um asset versionado da aplicação e entra
na imagem. A referência histórica Argel e os dados de clientes não entram na
imagem.

## 1. Criar a Application

No Coolify:

1. Entre no Project/Environment da demo e escolha **New Resource**.
2. Selecione o repositório pela GitHub App (recomendado para repositório
   privado) ou por Deploy Key.
3. Escolha a branch que contém esta documentação e o `Dockerfile`.
4. Configure:
   - **Build Pack:** `Dockerfile`
   - **Base Directory:** `/`
   - **Dockerfile Location:** `/Dockerfile`
   - **Port Exposes:** `8000`
5. Não defina Install, Build ou Start Command; use o `CMD` do `Dockerfile`.
6. Mantenha **uma única réplica**. A seleção da planilha fica em memória no
   processo, enquanto execuções e resultados ficam no volume.

O `Dockerfile` já expõe a porta 8000, escuta em `0.0.0.0` e contém um
healthcheck para `/api/health`.

Referências: [Dockerfile build pack][coolify-dockerfile],
[ports e configuração de Applications][coolify-apps] e
[healthchecks][coolify-health].

## 2. Adicionar o armazenamento persistente

Na aba **Persistent Storage**, adicione um **Volume**:

| Campo | Valor |
|---|---|
| Name | `report-generator9000-data` |
| Destination Path | `/app/data` |

O Master não pertence ao volume: ele já está na imagem e é somente para leitura.
O volume retém Gated Drop Folders, logs e relatórios entre deploys. Os registros
e outputs são descartados pela aplicação depois de sete dias. A planilha
enviada é temporária e deve ser reenviada após um restart ou redeploy.

Se a demo exigir Gated Drop Folders pré-carregados, use um Bind Mount em vez do
Volume e copie somente essas pastas para `<source>/gated/`. Não copie ou
substitua o Master no armazenamento persistente.

Referência: [Persistent Storage no Coolify][coolify-storage].

## 3. Configurar o ambiente

Na aba **Environment Variables**, use o Developer View e adicione:

```dotenv
GEMINI_API_KEY=COLOQUE_A_CHAVE_REAL_AQUI
GEMINI_MODEL=gemini-3.5-flash
GEMINI_FALLBACK_MODEL=gemini-3.5-flash-lite
GEMINI_OUTPUT_BUDGET=1024
GEMINI_TIMEOUT_SECONDS=60
GEMINI_MAX_ATTEMPTS=3
REPORT_DATA_ROOT=/app/data
REPORT_GATED_DROP_ROOT=/app/data/gated
REPORT_LOG_LEVEL=INFO
```

`GEMINI_API_KEY` é segredo de **runtime**: deixe **Build Variable desmarcado**.
Nenhuma variável dessa lista é necessária durante o build. Se os modelos
configurados não estiverem liberados para a chave da demo, troque-os por IDs
estáveis disponíveis nessa conta; não use aliases preview, experimental ou
`-latest`.

Não configure `REPORT_MASTER_PATH` no Coolify. Essa variável existe apenas como
override de emergência; o caminho normal é o Master empacotado com a aplicação.

Referência: [Environment Variables no Coolify][coolify-env].

## 4. Definir domínio e publicar

1. Atribua o domínio da demo à porta `8000`.
2. Ative HTTPS/Let's Encrypt e Force HTTPS.
3. Clique em **Deploy**. O primeiro build é pesado porque baixa as imagens de
   Node e Playwright.
4. Espere o estado ficar `Healthy`.

Não configure Port Mapping para o host. O domínio deve passar pelo proxy do
Coolify usando somente **Port Exposes 8000**.

## 5. Smoke test antes da apresentação

Substitua o domínio nos comandos:

```sh
curl --fail https://SEU-DOMINIO/api/health
```

A resposta esperada é:

```json
{"status":"ok"}
```

No Terminal da aplicação no Coolify, confirme o volume:

```sh
id
python -c "from report_generator9000.runs import PACKAGED_MASTER_PATH; assert PACKAGED_MASTER_PATH.is_file(); print(PACKAGED_MASTER_PATH)"
test -w /app/data/runs
test -w /app/data/outputs
```

Depois faça um teste completo pela interface:

1. envie uma cópia real da planilha;
2. escolha uma linha previamente conhecida como elegível;
3. aguarde todos os estágios;
4. baixe o `.docx`;
5. abra o documento no Word e confira imagens, textos e paginação.

Não faça redeploy ou restart entre o upload da planilha e o fim da geração. Os
arquivos de execução persistem, mas o índice da planilha enviada pertence ao
processo atual.

## Diagnóstico rápido

- **Application unhealthy:** confira se Port Exposes é `8000` e se nenhum Start
  Command substituiu o `CMD` do Dockerfile. Teste
  `http://127.0.0.1:8000/api/health` no Terminal.
- **Master ausente:** a imagem foi construída de um commit que não contém o
  asset versionado. Não faça upload manual; publique novamente o commit correto.
- **Geração para em Gemini:** confira `GEMINI_API_KEY`, acesso aos IDs de modelo
  e os logs da Application. Não habilite log `DEBUG` de `httpx` ou
  `google-genai`, pois os prompts podem aparecer nos logs.
- **Captura falha por memória:** aumente a RAM da VPS ou limite a carga da demo.
  A aplicação já limita o trabalho interno a duas gerações simultâneas.
- **Build demora ou usa muito disco:** é esperado no primeiro build da imagem
  Playwright. Preserve o build cache do Coolify e não habilite
  `SOURCE_COMMIT` como build argument sem necessidade.

[coolify-dockerfile]: https://coolify.io/docs/applications/build-packs/dockerfile
[coolify-apps]: https://coolify.io/docs/applications/
[coolify-health]: https://coolify.io/docs/knowledge-base/health-checks
[coolify-storage]: https://coolify.io/docs/knowledge-base/persistent-storage
[coolify-env]: https://coolify.io/docs/knowledge-base/environment-variables
