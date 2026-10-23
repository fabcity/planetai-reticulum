FROM python:3.12-slim
# Pinned to what node #1 ran on 23 Oct 2026. rns and lxmf are under the Reticulum License, which is not an open
# licence: read NOTICE before you move either pin, and read LICENSE at the new tag.
RUN pip install --no-cache-dir rns==1.5.4 lxmf==1.1.1 httpx==0.28.1
WORKDIR /app
COPY reticulum_bridge.py .
EXPOSE 4242 4243
CMD ["python", "reticulum_bridge.py"]
