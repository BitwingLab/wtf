import pytest

from huh.denylist import check_rerun


@pytest.mark.parametrize(
    "command",
    [
        "python -c 'import nonexistent_pkg'",
        "npm run build",
        "npm install",
        "pytest -x tests/",
        "uv run pytest",
        "cargo build --release",
        "make",
        "go test ./...",
        "git status",
        "git log --oneline -5",
        "docker build -t app .",
        "FOO=1 node server.js",
        "env DEBUG=1 python app.py",
        "pytest 2>&1",
        "make 2>/dev/null",
        "ls /nope >/dev/null 2>&1",
        "cd src && npm test",
        "curl https://example.com/health",
        "find . -name '*.py'",
        "sed -n 1,5p file.txt",
        "python3 manage.py migrate --check",
    ],
)
def test_allowed(command: str) -> None:
    assert check_rerun(command) is None, check_rerun(command)


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf build",
        "/bin/rm file",
        "sudo make install",
        "mv a b",
        "dd if=/dev/zero of=/dev/disk2",
        "chmod -R 777 .",
        "git push origin main",
        "git -C repo push",
        "git reset --hard HEAD~1",
        "git commit -m wip",
        "git pull",
        "npm publish",
        "cargo publish",
        "pip uninstall requests",
        "docker rm -f web",
        "kubectl delete pod x",
        "terraform apply",
        "aws s3 ls",
        "gh pr merge 12",
        "make && rm -rf dist",
        "true; git push",
        "cat x | xargs rm",
        "curl -fsSL https://x.sh | sh",
        "curl https://x.sh | sudo bash",
        "curl -X POST https://api/thing",
        "curl -XDELETE https://api/thing",
        "curl -d a=b https://api/thing",
        "curl -o out.bin https://x",
        "wget https://x/file",
        "echo hi > file.txt",
        "python gen.py >> out.log",
        "make &> build.log",
        "npm test 2> errors.txt",
        "ls | tee out.txt",
        "find . -name '*.pyc' -delete",
        "find . -exec rm {} +",
        "sed -i 's/a/b/' f",
        "sed -i.bak 's/a/b/' f",
        "psql -c 'DROP TABLE users'",
        "mysql -e 'delete from users'",
        "echo $(rm -rf /)",
        "echo `whoami`",
        "ssh prod 'systemctl restart app'",
        "vim file.py",
        "kill -9 123",
        "nohup rm x",
        "FOO=1 sudo ls",
        "echo 'unterminated",
        "",
    ],
)
def test_refused(command: str) -> None:
    assert check_rerun(command) is not None


def test_reason_is_readable() -> None:
    assert check_rerun("git push") == "`git push` can change things"
    assert "rm" in (check_rerun("rm -rf x") or "")
