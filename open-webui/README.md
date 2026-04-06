# Open WebUI

Stack locale per avviare Open WebUI con Docker Compose.

## Accesso

Il servizio e' esposto su:

- `http://localhost:3000`

Una volta avviato, l'interfaccia web e' disponibile dal browser su quella porta.

## Comandi

Dalla cartella `open-webui/`:

```sh
./up.sh
./down.sh
./redeploy.sh
```

- `up.sh`: avvia il servizio in background
- `down.sh`: ferma e rimuove il container
- `redeploy.sh`: scarica l'immagine piu' recente e ricrea il container

## Dati

I dati applicativi sono persistiti in un volume Docker nominato (`open-webui`).
