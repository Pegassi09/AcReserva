# AC Reserva

Sistema de reserva de salas preparado para Vercel. A página é estática e a API é uma Vercel Function Python; por isso não depende de runtime PHP comunitário. A persistência é MongoDB Atlas, pois o sistema de arquivos de uma Function é efêmero e não serve para armazenar reservas.

## Publicar na Vercel

1. Crie um cluster MongoDB Atlas (o plano gratuito é suficiente para começar) e um usuário de banco.
2. Copie a URI de conexão do Atlas e autorize as conexões da Vercel na rede do cluster.
3. Na Vercel, importe este diretório/repositório. Não configure Build Command nem Output Directory.
4. Em **Settings → Environment Variables**, cadastre `MONGODB_URI`, `MONGODB_DB` e `JWT_SECRET` para Preview e Production, conforme `.env.example`.
5. Faça o deploy. A Vercel identifica `api/index.py` como uma Function Python, que serve o frontend e as rotas `/api/*`. Não configure rewrites, Build Command ou Output Directory. As coleções e índices são criados automaticamente na primeira chamada.
6. Na primeira abertura, escolha **ACIM** → **Acesso administrativo** → **Primeiro acesso**. Crie o administrador inicial: a aplicação só permite essa ação enquanto não existir nenhum usuário. A sessão será iniciada automaticamente.

Para publicar pela CLI, após instalar a CLI e autenticar:

```sh
vercel deploy
vercel deploy --prod
```

## Variáveis obrigatórias

| Variável | Uso |
| --- | --- |
| `MONGODB_URI` | URI de conexão MongoDB Atlas, incluindo usuário, senha e cluster. |
| `MONGODB_DB` | Nome do banco, por padrão `ac_reserva`. |
| `JWT_SECRET` | Assinatura dos tokens de sessão. Use valor aleatório longo. |
| `ALLOWED_ORIGINS` | Domínio(s) autorizado(s) a chamar a API. |

## Antes do primeiro acesso

O arquivo `.env.example` não contém credenciais reais. Sem `MONGODB_URI`, a tela de primeiro acesso não pode criar o administrador nem guardar reservas. Consulte [a estrutura NoSQL](database/mongodb.md) para as coleções e garantias de concorrência.

## Se aparecer erro ao entrar

Abra `https://SEU-DOMINIO/api/health`. O resultado deve trazer `"configuration_ready": true`. Se estiver `false`, em **Vercel → Settings → Environment Variables** cadastre `MONGODB_URI` e `JWT_SECRET` para o ambiente que está sendo acessado (Preview ou Production) e faça um novo deploy. Se ambos estiverem configurados, consulte **Vercel → Logs → Functions**: a API agora devolve uma mensagem específica para falhas de conexão com o MongoDB e registra o detalhe técnico no log.

## Endpoints principais

`GET /api/health`, `GET /api/setup/status`, `POST /api/setup/admin`, `GET /api/public/sectors`, `POST /api/auth/login`, `GET /api/me`, `GET/POST /api/reservations`, `POST /api/reservations/{id}/cancel`, `GET /api/rooms` e `GET /api/dashboard`.

As regras de limite mensal, semanas consecutivas, conflito de sala/equipamento e autorização são verificadas dentro da API em transações MongoDB. A interface apenas apresenta o resultado; ela não é a fonte de segurança.

## Integração Google Calendar

O banco mantém `google_calendar_event_id` para impedir duplicação. A sincronização deve ser ativada somente após cadastrar `GOOGLE_CALENDAR_ID` e uma credencial de conta de serviço em `GOOGLE_SERVICE_ACCOUNT_JSON`; as permissões do calendário devem ser concedidas explicitamente à conta de serviço.
