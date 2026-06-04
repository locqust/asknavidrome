FROM alpine:3.22.1 AS build
LABEL maintainer="locqust"
LABEL org.opencontainers.image.source=https://github.com/locqust/asknavidrome

RUN apk add python3 py3-pip build-base python3-dev libffi-dev openssl-dev

WORKDIR /opt

RUN python3 -m venv env

# Copy the skill source from the build context (this repo)
# rather than cloning upstream, so local changes are included.
COPY skill /opt/asknavidrome/skill

WORKDIR /opt/asknavidrome

RUN source ../env/bin/activate && pip --no-cache-dir install wheel && pip --no-cache-dir install -r skill/requirements-docker.txt


FROM alpine:3.22.1
LABEL maintainer="locqust"
LABEL org.opencontainers.image.source=https://github.com/locqust/asknavidrome

RUN apk add python3

COPY --from=build /opt/env /opt/env
COPY --from=build /opt/asknavidrome/skill /opt/asknavidrome/

WORKDIR /opt/asknavidrome

# Activate Python Virtual Environment
ENV PATH="/opt/env/bin:$PATH"

EXPOSE 5000

ENTRYPOINT ["python3", "app.py"]