# Agent Zero

Stack locale per avviare Agent Zero con Docker Compose.

## Accesso

Il servizio e' esposto su:

- `http://localhost:50080`

Una volta avviato, l'interfaccia web e' disponibile dal browser su quella porta.

## Comandi

Dalla cartella `agent-zero/`:

```sh
./up.sh
./down.sh
./redeploy.sh
```

- `up.sh`: avvia il servizio in background
- `down.sh`: ferma e rimuove il container
- `redeploy.sh`: scarica l'immagine piu' recente e ricrea il container

## Dati

I dati persistenti sono salvati nella cartella locale `agent-zero/data/`, montata nel container come `/a0/usr`.

## Model API Base URL

Se il model server gira sul Mac host, dentro Agent Zero va usato:

- `http://host.docker.internal:11434`

Questo succede perche' `localhost` dentro il container punta al container stesso, non al Mac host.

Per verificare che il servizio modello sia raggiungibile dal Mac, puoi provare:

```sh
curl http://localhost:11434/api/tags
```

Se il model server gira invece in un altro container Docker, usa il nome del servizio Docker, per esempio:

- `http://ollama:11434`
