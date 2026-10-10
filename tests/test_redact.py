import pytest

from huh.redact import REDACTED, redact

# Assembled at runtime so this file doesn't itself look like it contains secrets.
ANTHROPIC = "sk-ant-api03-" + "a1B2c3D4e5F6g7H8i9J0" * 3
OPENAI = "sk-proj-" + "Zx9Yw8Vu7Ts6Rq5Po4Nm3Lk2" * 2
OPENAI_LEGACY = "sk-" + "abcdefghijklmnopqrstuvwxyz012345"
GITHUB_PAT = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
GITHUB_FINE = "github_pat_" + "11ABCDEFG0" + "x" * 50
AWS_ID = "AKIA" + "IOSFODNN7EXAMPLE"
AWS_SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"


@pytest.mark.parametrize(
    "secret",
    [ANTHROPIC, OPENAI, OPENAI_LEGACY, GITHUB_PAT, GITHUB_FINE, AWS_ID],
)
def test_token_formats_removed(secret: str) -> None:
    out = redact(f"error: auth failed using {secret} while connecting")
    assert secret not in out
    assert REDACTED in out
    assert out.startswith("error: auth failed using ")
    assert out.endswith(" while connecting")


def test_gho_ghs_ghu_ghr_tokens() -> None:
    for prefix in ("gho_", "ghs_", "ghu_", "ghr_"):
        token = prefix + "Q" * 36
        assert token not in redact(f"token is {token}")


def test_bearer_header() -> None:
    out = redact("curl -H 'Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig' https://x")
    assert "eyJhbGciOiJIUzI1NiJ9" not in out
    assert "Authorization: Bearer [REDACTED]" in out


def test_bare_bearer() -> None:
    out = redact("sent header bearer abcdefghijklmnop1234")
    assert "abcdefghijklmnop1234" not in out


def test_basic_auth_header() -> None:
    out = redact("Authorization: Basic dXNlcjpwYXNzd29yZA==")
    assert "dXNlcjpwYXNzd29yZA" not in out


@pytest.mark.parametrize(
    "url,leaked",
    [
        ("postgres://admin:hunter2@db.example.com:5432/app", "hunter2"),
        ("https://user:p%40ss@github.com/org/repo.git", "p%40ss"),
        ("redis://:s3cret@localhost:6379", None),  # empty user: left alone, no false crash
        ("mongodb+srv://bob:Tr0ub4dor@cluster0.mongodb.net", "Tr0ub4dor"),
    ],
)
def test_passwords_in_urls(url: str, leaked: str | None) -> None:
    out = redact(f"could not connect to {url}")
    if leaked:
        assert leaked not in out
        assert f":{REDACTED}@" in out


def test_url_without_credentials_unchanged() -> None:
    text = "fetch failed: https://registry.npmjs.org/left-pad and http://localhost:3000/a@b"
    assert redact(text) == text


@pytest.mark.parametrize(
    "line,value",
    [
        ("ANTHROPIC_API_KEY=abc123def456", "abc123def456"),
        ("export GITHUB_TOKEN=gh-something-123", "gh-something-123"),
        ("DB_PASSWORD='correct horse'", "correct"),
        ('SECRET_KEY_BASE="a8f5f167f44f4964e6c998dee827110c"', "a8f5f167f44f"),
        (f"AWS_SECRET_ACCESS_KEY={AWS_SECRET}", AWS_SECRET),
        ("STRIPE_KEY: rk_live_123456", "rk_live_123456"),
        ("password=hunter2", "hunter2"),
        ("access_token: abc.def.ghi", "abc.def.ghi"),
        ('{"apiKey": "zzz-111-yyy"}', "zzz-111-yyy"),
        ('{"client_secret": "shh"}', "shh"),
        ("MYSQL_ROOT_PWD=toor", "toor"),
        ("KEY=plainvalue", "plainvalue"),
    ],
)
def test_secret_assignments(line: str, value: str) -> None:
    out = redact(line)
    assert value not in out, out
    assert REDACTED in out


def test_assignment_keeps_name() -> None:
    assert redact("OPENAI_API_KEY=xyz789") == f"OPENAI_API_KEY={REDACTED}"


@pytest.mark.parametrize(
    "text",
    [
        "KeyError: 'username'",
        "TokenError: unexpected EOF",
        "KEYBOARD=us",
        "max_tokens: 1024",
        "MAX_TOKENS=4096",
        "primary_key: id",
        "PWD=/home/me/project",
        "Enter password:\nnext line stays",
        "if token == expected:",
        'psql: error: FATAL: password authentication failed for user "me"',
        "npm ERR! code ENOENT",
        "ModuleNotFoundError: No module named 'nonexistent_pkg'",
        "author: Jane",
        "monkey=3",
    ],
)
def test_no_false_positives(text: str) -> None:
    assert redact(text) == text


def test_cli_flags() -> None:
    out = redact("mysql --password=s3cr3t --user root && tool --token abc123")
    assert "s3cr3t" not in out
    assert "abc123" not in out
    assert "--user root" in out


def test_pem_private_key() -> None:
    pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA\nabc\n-----END RSA PRIVATE KEY-----"
    out = redact(f"loading key:\n{pem}\ndone")
    assert "MIIEpAIBAAKCAQEA" not in out
    assert out == f"loading key:\n{REDACTED}\ndone"


def test_public_key_kept() -> None:
    text = "-----BEGIN PUBLIC KEY-----\nMFkwEw\n-----END PUBLIC KEY-----"
    assert redact(text) == text


def test_multiple_secrets_in_dotenv() -> None:
    env = (
        f"ANTHROPIC_API_KEY={ANTHROPIC}\n"
        "DEBUG=true\n"
        "DATABASE_URL=postgres://u:pw123@h/db\n"
        "PORT=8080\n"
    )
    out = redact(env)
    assert ANTHROPIC not in out
    assert "pw123" not in out
    assert "DEBUG=true" in out
    assert "PORT=8080" in out


def test_idempotent() -> None:
    text = f"KEY={ANTHROPIC} Authorization: Bearer abcdefghijklmnop https://a:b@c"
    once = redact(text)
    assert redact(once) == once
    assert f"{REDACTED}]" not in once  # no nested markers


def test_empty() -> None:
    assert redact("") == ""
