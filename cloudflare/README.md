# Cloudflare Tunnel for Run Trainer

## Install cloudflared
```bash
brew install cloudflared # macOS
# or
sudo apt-get install cloudflared
```

## Authenticate and create tunnel
```bash
cloudflared tunnel login
cloudflared tunnel create runtrainer
```

## Example config
Place at `~/.cloudflared/config.yml`:
```yaml
tunnel: runtrainer
credentials-file: ~/.cloudflared/runtrainer.json
ingress:
  - hostname: api.runtrainer.local
    service: http://localhost:8000
  - hostname: app.runtrainer.local
    service: http://localhost:3000
  - service: http_status:404
```

## Run the tunnel
```bash
cloudflared tunnel run runtrainer
```

## Production notes
- Create DNS CNAMEs for `api.yourdomain.com` and `app.yourdomain.com` pointing to the Cloudflare tunnel.
- Update the `hostname` entries in the config to match your real subdomains.
