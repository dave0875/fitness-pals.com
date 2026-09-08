# Cloudflare Tunnel (containerized)

The tunnel now runs as a service defined in `compose.yml` (`cloudflared`) using a **tunnel token**. No local `cloudflared` install or config file is required on the host.

## Steps
1. In Cloudflare Zero Trust, create a remotely managed tunnel and copy its token.
2. Add the token to your `.env`:
   ```
   CLOUDFLARE_TUNNEL_TOKEN=xxxxxxxx
   ```
3. Configure the tunnel's published application routes in Cloudflare Zero Trust. Origins must use Compose service DNS names, never container IP addresses or `127.0.0.1`:

   | Dev hostname | Origin service |
   | --- | --- |
   | `test.fitness-pals.com` | `http://frontend:3000` |
   | `api-test.fitness-pals.com` | `http://backend:8000` |
   | `training-api-test.fitness-pals.com` | `http://training-agent:9000` |
   | `auth-test.fitness-pals.com` | `http://authentik-server:9000` |

   Production routes follow the same service-name rule and are documented in `config.yml`.
4. Bring up the stack:
   ```
   docker compose up -d cloudflared
   ```
   The container runs `cloudflared tunnel run` with the provided token and forces `--protocol http2` to avoid QUIC/UDP buffer issues common on WSL/Windows hosts.

## Notes
- A token starts a remotely managed tunnel, so the published routes in Cloudflare Zero Trust are authoritative. The mounted `config.yml` documents the production route contract but does not override remotely managed routes.
- Container IP addresses are ephemeral. `127.0.0.1` inside `cloudflared` is the tunnel container itself, not another Compose service.
- DNS: point your desired hostnames (e.g., `app.example.com`, `api.example.com`) to the tunnel via Cloudflare DNS as usual.
- CI/CD deploys now require `CLOUDFLARE_SMOKE_URLS` in the deployment `.env`. Set it to the public health/readiness URLs that should work through the tunnel, for example:
  ```
  CLOUDFLARE_SMOKE_URLS=https://api.fitness-pals.com/ready,https://grafana.fitness-pals.com/api/health
  ```
  You can also provide one URL per line in the env file. Optional `CLOUDFLARE_SMOKE_TIMEOUT_SECONDS` overrides the default 90 second wait.
