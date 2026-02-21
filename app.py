from fastapi import FastAPI

app = FastAPI(title="Marketplace Gateway")


@app.get("/health")
def health():
    return {"status": "ok"}
