# Changelog

## 0.1.0 - 2026-10-31

Primeira versão publicada, por Leandro Garcia, a partir da primeira versão de Filipe.

Da versão de Filipe (`whatsapp-desktop-local`): leitura do banco do WhatsApp Desktop do Mac, download e decifragem da mídia que o app não baixou, transcrição local com whisper.cpp e as regras de uso da skill.

Novo nesta versão:
- Fonte WAHA, além do app do Mac, e contas nomeadas (mais de um número).
- Pasta de dados configurável; a API key do WAHA fica fora do config.
- Exportação para Markdown, `Anexos/` e `Mensagens.json`, juntando pelo id do WhatsApp sem perder histórico.
- `wa sync` por nome, número ou grupo, com o id gravado na primeira resolução.
- Integração opcional com o plugin Obsidian CRM.
- `wa agendar` (launchd, systemd ou cron), instalador e testes com fontes falsas.
