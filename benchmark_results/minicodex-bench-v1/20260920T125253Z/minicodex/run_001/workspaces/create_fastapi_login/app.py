"""FastAPI login service."""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Login Service")

# Demo credential store: username -> password
USERS = {
    "demo": "demo",
}


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str


@app.post("/login", response_model=LoginResponse)
def login(credentials: LoginRequest) -> LoginResponse:
    """Authenticate a user and return an access token."""
    expected = USERS.get(credentials.username)
    if expected is None or expected != credentials.password:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = f"token-{credentials.username}"
    return LoginResponse(token=token)
