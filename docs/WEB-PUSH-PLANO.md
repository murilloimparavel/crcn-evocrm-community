# Plano: notificações Web Push do EvoCRM

## Estado observado

- O agregador fixa o CRM em `5e38d40` e o Sofia em `3ff291e`. O CRM recebe mensagens e cria notificações para os destinatários conforme as regras de conversa e preferências; `Notification::PushNotificationJob` envia em segundo plano.
- O CRM já tem `web-push`, `VapidService`, `NotificationSubscription` e `POST /api/v1/notification_subscriptions`. O payload de navegador só contém título, tag e URL; o corpo com remetente e prévia já é produzido por `Notification#push_message_body` para outros canais.
- O endpoint de exclusão procura apenas token FCM e não restringe a consulta ao usuário atual. Os logs de inscrição registram atributos de assinatura. A chave pública VAPID está no dashboard Rails, mas não no endpoint público de configuração consumido pelo Sofia.
- O Sofia pede permissão no perfil e mostra notificações via WebSocket enquanto a aplicação está aberta; não há inscrição PushManager, service worker ou manifesto PWA no commit analisado. A rota do Sofia é `/conversations/:conversationId`, enquanto a URL enviada pelo CRM começa com `/app/conversations/`.
- iOS/iPadOS exige aplicativo adicionado à tela inicial e solicitação de permissão em interação do usuário; Web Push requer contexto seguro e um service worker ativo. Fonte: https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/ e https://developer.mozilla.org/en-US/docs/Web/API/Push_API.

## Solução proposta

1. Reaproveitar notificações e preferências existentes. Expor apenas a chave pública VAPID por API, manter chave privada estável no servidor e documentar configuração, HTTPS e dependências de rede.
2. Proteger o ciclo de vida das inscrições: validar tipo e atributos, limitar exclusão ao usuário autenticado e ao endpoint informado, evitar registrar endpoints e chaves nos logs, suportar dispositivos múltiplos, troca de usuário, renovação, expiração e saída de sessão com tratamento explícito de falha.
3. Enviar remetente e prévia já fornecidos pelo modelo, com fallback para anexos e mensagens sem conteúdo. Corrigir destino para a rota do Sofia e permitir apenas navegação interna segura. Tratar preferências ausentes, assinaturas inválidas e falhas transitórias sem apagar inscrições válidas; considerar mensagens repetidas e concorrência.
4. Adicionar manifesto e ícones instaláveis, service worker para receber e apresentar push e abrir ou focar a conversa, e inscrição por interação explícita no perfil. Mostrar estados reais de suporte, permissão e inscrição, oferecer desativação e instruções para instalação no iOS. Coordenar com a notificação WebSocket para evitar duplicações sem perder alertas.
5. Manter autorização e isolamento por usuário/conta, respeitar preferências existentes e limitar a exposição de conteúdo em notificações e logs. Documentar comportamento em tela bloqueada e condições de entrega e disponibilidade.
6. Validar com testes direcionados de payload, destinatários, autorização, inscrição/cancelamento e service worker; executar testes e builds relevantes dos módulos; revisar diff e regressões. Validar em navegadores compatíveis e aparelhos Android e iOS instalados, inclusive app fechado, toque, logout, expiração e falhas de rede, quando houver ambiente e dispositivos disponíveis.
7. Fazer commits por unidade coerente em cada repositório; revisar remotes, branches, CI e gitlinks individualmente. O push deve seguir somente para remotes autorizados. Push não implica deploy; produção exige verificar o mecanismo, saúde e rollback conforme as instruções locais.

## Critérios de aceite

- Um usuário autenticado pode ativar e desativar o push no próprio aparelho; o estado apresentado reflete uma inscrição efetiva, não apenas a permissão do navegador.
- Ao chegar uma mensagem elegível, destinatários autorizados e com preferência ativa recebem notificação com remetente e prévia ou descrição do anexo, mesmo com a aplicação fechada. O toque abre a conversa correta.
- Múltiplos dispositivos funcionam independentemente; logout, troca de usuário, revogação e inscrições expiradas não vazam dados nem removem inscrições de terceiros.
- Fluxo funciona em HTTPS em Android compatível e em web app instalado no iOS/iPadOS compatível, com orientações claras quando não suportado ou bloqueado.
- Testes automatizados relevantes, revisão de segurança e evidência de validação nos aparelhos acompanham a entrega; limitações são explicitadas sem apresentar verificações simuladas como testes reais.
