# Operação de Web Push

## Pré-requisitos

- O Sofia precisa ser servido em HTTPS, com `/manifest.webmanifest`, `/push-worker.js` e os ícones acessíveis na mesma origem. O service worker não armazena conteúdo em cache.
- Defina `FRONTEND_URL` com a URL HTTPS pública do Sofia para o CRM **e** para o processo Sidekiq. Opcionalmente defina `VAPID_SUBJECT` como URL HTTPS ou `mailto:` de contato; quando ausente, o CRM usa `FRONTEND_URL`. Em desenvolvimento HTTP local, configure um `VAPID_SUBJECT` válido.
- O CRM mantém um par VAPID estável em `InstallationConfig`; preserve o banco e os segredos em backups. Não publique a chave privada. Se configurar chaves por ambiente, forneça o par completo e consistente em todos os processos antes da criação inicial; alterar apenas as variáveis depois da criação não substitui o par persistido.
- O Sidekiq precisa consumir a fila `default` e ter saída HTTPS para os serviços de push de Google, Mozilla, Apple e Windows usados pelos navegadores. Não registre endpoints nem chaves de inscrições em logs.
- Cada usuário ativa as notificações no perfil, no dispositivo desejado, e seleciona os tipos de evento. No iPhone/iPad compatível, instale Sofia na Tela de Início, abra o aplicativo instalado e faça a ativação a partir dele.

## Verificação

O Sofia inclui `npm run test:webpush-browser`, que entrega um evento de push simulado ao service worker em Chromium e verifica o conteúdo exibido. O teste usa apenas um servidor local; ele não comprova entrega pelo serviço de push nem substitui os testes em celulares. Use `CHROMIUM_EXECUTABLE_PATH` se o Chromium completo não estiver na localização padrão do Playwright.

1. Confirme que CRM e Sidekiq usam a mesma configuração e que o domínio público do frontend corresponde à origem usada no dispositivo.
2. Entre com um usuário autorizado, ative notificações no perfil e habilite as preferências de nova conversa e nova mensagem que deseja receber.
3. Com o aplicativo fechado, envie uma mensagem de teste para uma conversa elegível; confira remetente, prévia ou indicação de anexo e abertura da conversa ao tocar.
4. Repita em Android e em aplicativo instalado no iPhone/iPad; teste ainda múltiplos dispositivos, cancelamento, logout, revogação e indisponibilidade de rede. A entrega depende do navegador, do sistema operacional e dos serviços de push; não é garantida imediatamente.
5. Verifique logs do Sidekiq sem dados pessoais: uma falha de autenticação VAPID indica configuração ou par de chaves incompatível; uma inscrição expirada é removida e pode ser refeita no dispositivo. Não apague todas as inscrições diante de erro de autenticação.

A prévia pode aparecer na tela bloqueada do aparelho conforme as configurações do sistema. Oriente os usuários a proteger o dispositivo e ajustar a exibição de prévias no sistema operacional.
