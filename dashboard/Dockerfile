# ---------------------------------------------------------------------------
# GPS_Tracer dashboard
#
# Two stages, and the second one installs nothing at all.
#
# `server.mjs` is written against Node's standard library only — no Express, no
# http-proxy, no dotenv. That is deliberate rather than an affectation: this
# process holds the tachograph service token and forwards a user's identity
# based on their Traccar session, so it is the one component where "how many
# packages am I trusting?" is a question worth answering with zero. The result is
# also what makes the runtime stage possible without a package manager.
#
# The browser bundle (React + MapLibre) is built in stage one and its
# dependencies never reach stage two.
# ---------------------------------------------------------------------------

FROM node:22-alpine AS build

WORKDIR /app

# Dependencies first so this layer is cached until the manifest changes.
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY index.html vite.config.js server.mjs ./
COPY src ./src
RUN npm run build


FROM node:22-alpine

ENV NODE_ENV=production

WORKDIR /app

# Only the build output and the server. No node_modules: there are no runtime
# dependencies to install.
COPY --from=build /app/dist ./dist
COPY server.mjs ./

# The image is read-only in practice. `node` is a non-root user that already
# exists in the official image.
USER node

# The dashboard port. Published to loopback by docker-compose; a reverse proxy
# terminates TLS in front of it.
EXPOSE 8083

# `server.mjs` refuses tachograph requests when TACHO_API_TOKEN is unset rather
# than serving them unauthenticated, so a misconfigured container degrades the
# tachograph tabs and keeps the fleet map working. That is the intended failure.
CMD ["node", "server.mjs"]
