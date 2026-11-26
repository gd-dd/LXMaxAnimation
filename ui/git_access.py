"""Read the Git identity and, on request, the credential's GitHub account and repository role."""
import json
from pathlib import Path
import re
import subprocess
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from . import integrations as git


_GIT_FAILURES = (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired)
_GITHUB_URL = re.compile(r"https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/?", re.I)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        # Authorization must stay on the exact GitHub API origin.
        return None


def _github_target(remote):
    match = _GITHUB_URL.fullmatch(remote)
    if not match:
        return None
    owner, repo = match.groups()
    if repo.lower().endswith(".git"):
        repo = repo[:-4]
    if owner in (".", "..") or repo in ("", ".", ".."):
        return None
    return owner, repo


def _safe_remote(remote):
    if not remote:
        return ""
    target = _github_target(remote)
    if target:
        return "https://github.com/" + "/".join(target)
    try:
        address = urlsplit(remote)
        if address.scheme in ("http", "https", "ssh") and address.hostname:
            return address.scheme + "://" + address.hostname
    except ValueError:
        pass
    return "其他 Git 地址"


def _local(root, *args):
    try:
        return git.git_run(root, *args, timeout=5)
    except _GIT_FAILURES:
        return ""


def _cached_token(root, remote):
    # The supplied URL excludes credentials. Git derives the matching helper context,
    # including repository path when credential.useHttpPath is enabled.
    result = git.git_run(
        root, "-c", "core.askPass=", "credential", "fill", timeout=8, strip=False, input=f"url={remote}\n\n",
        extra_env={
            "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "0", "GCM_GUI_PROMPT": "0",
            "GIT_ASKPASS": "", "SSH_ASKPASS": "", "GIT_TRACE": "0", "GIT_TRACE_CURL": "0",
            "GIT_CURL_VERBOSE": "0", "GIT_TRACE2": "0", "GIT_TRACE2_EVENT": "0",
            "GCM_TRACE": "0", "GCM_TRACE_SECRETS": "0", "GCM_DEBUG": "0",
        },
    )
    fields = dict(line.split("=", 1) for line in result.splitlines() if "=" in line)
    token = fields.get("password")
    if not token and fields.get("authtype", "").lower() == "bearer":
        token = fields.get("credential")
    return token if token and re.fullmatch(r"[!-~]{1,4096}", token) else None


def _api(path, token):
    request = Request(
        "https://api.github.com" + path,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "User-Agent": "LXMaxAnimation",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with build_opener(_NoRedirect()).open(request, timeout=8) as response:
        raw = response.read(262145)
    if len(raw) > 262144:
        raise ValueError("GitHub API response exceeds limit")
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError("Invalid GitHub API response")
    return result


def _api_problem(error):
    headers = error.headers or {}
    code = error.code
    error.close()
    if headers.get("X-GitHub-SSO"):
        return "组织要求单点登录（SSO）授权。请在 GitHub 完成组织授权后重新检查。"
    if code == 401:
        return "当前 GitHub 凭据已过期、失效或被撤销。请在 LXGit 登录正确的 GitHub 账号。"
    if code == 429 or headers.get("X-RateLimit-Remaining") == "0":
        return "GitHub 暂时限制访问次数，请稍后重新检查。"
    if code == 404:
        return "GitHub 未返回该仓库。请核对共享库地址、私有仓库邀请及当前账号的访问权限。"
    if code == 403:
        return "GitHub 拒绝访问。请核对仓库邀请、组织授权及当前凭据的权限。"
    if 300 <= code < 400:
        return "GitHub 返回了跳转。请核对仓库是否改名或迁移，并更新共享库地址。"
    return f"GitHub 暂时无法核对账号或仓库权限（HTTP {code}）。"


def access_state(root, verify=False):
    """Return display-safe fields. The default checks local configuration only."""
    identity = _local(root, "var", "GIT_COMMITTER_IDENT")
    who = re.fullmatch(r"(.*) <([^<>]+)> \d+ [+-]\d{4}", identity)
    name, email = who.groups() if who else (
        _local(root, "config", "--get", "user.name"),
        _local(root, "config", "--get", "user.email"),
    )
    linked = (Path(root)/".git").exists()
    remote = _local(root, "remote", "get-url", "origin") if linked else ""
    push = _local(root, "remote", "get-url", "--push", "--all", "origin").splitlines() if remote else []
    target = _github_target(remote)
    push_target = _github_target(push[0]) if len(push) == 1 else None
    helper = bool(_local(root, "config", "--get-urlmatch", "credential.helper", remote)) if target else False
    state = dict(
        identity_name=name, identity_email=email, identity_ready=bool(who),
        remote=_safe_remote(remote),
        push_remote=_safe_remote(push[0]) if len(push) == 1 else ("多个推送地址" if push else ""),
        helper_configured=helper, account="", read_access=None, write_access=None,
        verified=False, message="",
    )
    if not remote:
        state["message"] = "当前本地库尚未配置 GitHub 共享地址。"
        return state
    if target is None:
        state["message"] = "请在共享设置使用不含嵌入凭据的 GitHub HTTPS 仓库地址。"
        return state
    if not verify:
        state["message"] = "提交者用于版本署名。点击「检查 GitHub 权限」可核对 Git 当前使用的 GitHub 账号。"
        return state
    state["verified"] = True

    try:
        token = _cached_token(root, remote)
    except _GIT_FAILURES:
        token = None
    if not token:
        state["message"] = "当前 Git 未提供可用的 GitHub 凭据。请在 LXGit 登录 GitHub，再回来检查。"
        return state

    try:
        user = _api("/user", token)
        login = user.get("login")
        if isinstance(login, str) and re.fullmatch(r"[A-Za-z0-9-]{1,39}(?:\[bot\])?", login):
            state["account"] = login
        repo = _api("/repos/" + "/".join(target), token)
    except HTTPError as error:
        state["message"] = _api_problem(error)
        return state
    except (URLError, OSError, ValueError):
        state["message"] = "暂时无法连接 GitHub 或读取权限。请检查网络后重试。"
        return state

    permissions = repo.get("permissions")
    if isinstance(permissions, dict):
        read = permissions.get("pull")
        if isinstance(read, bool):
            state["read_access"] = read
    same_destination = push_target and tuple(map(str.casefold, push_target)) == tuple(map(str.casefold, target))
    if not same_destination:
        state["message"] = "读取地址和推送地址不同，当前只检查了共享库的读取地址。请在 LXGit 核对推送地址。"
    elif repo.get("archived") or repo.get("disabled"):
        state["write_access"] = False
        state["message"] = "共享仓库已归档或停用，无法推送。请联系仓库管理员。"
    else:
        write = permissions.get("push") if isinstance(permissions, dict) else None
        if isinstance(write, bool):
            state["write_access"] = write
        if write is True:
            state["message"] = "GitHub 显示该账号有仓库写权限。分支规则及凭据范围仍会在推送时校验。"
        elif write is False:
            state["message"] = "GitHub 显示该账号没有仓库写权限。请联系仓库管理员确认访问角色。"
        else:
            state["message"] = "已读取仓库信息。GitHub 未返回当前账号的写权限状态。"
    return state


def describe_git_error(error):
    """Map common sync failures and redact embedded authentication material."""
    text = str(error).strip()
    lower = text.casefold()
    if isinstance(error, subprocess.TimeoutExpired):
        return "Git 操作超时。请检查网络或 Git 登录状态后重试。"
    if any(term in lower for term in ("gh006", "gh013", "protected branch", "repository rule violations")):
        return "GitHub 分支保护或仓库规则拒绝了推送。请联系管理员核对 main 的规则。"
    if "saml" in lower or ("sso" in lower and "authorization" in lower):
        return "组织要求单点登录（SSO）授权。请在 GitHub 完成组织授权后重试。"
    if any(term in lower for term in ("authentication failed", "authentication required", "could not read username",
            "terminal prompts disabled", "support for password authentication", "invalid username or token",
            "error: 401")):
        return "GitHub 凭据不可用。请在「账号与权限」核对 Git 当前账号，或在 LXGit 登录。"
    if any(term in lower for term in ("repository not found", "error: 404")):
        return "找不到共享库或当前账号无权访问。请核对 GitHub 仓库地址、账号和私有仓库邀请。"
    if any(term in lower for term in ("write access to repository not granted", "denied to ", "error: 403")):
        return "GitHub 拒绝访问。请在「账号与权限」核对账号、仓库写权限和组织授权。"
    safe = re.sub(r"(?i)\b((?:https?|ssh)://)[^/\s'\"]+@", r"\1", text)
    safe = re.sub(r"(?i)(\b(?:https?|ssh)://[^\s'\"?]+)\?[^\s'\"]*", r"\1", safe)
    safe = re.sub(r"(?i)\b(bearer|basic)\s+[-\w.+/=]+", r"\1 [已隐藏]", safe)
    return re.sub(r"\b(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]+", "[已隐藏]", safe)[-4000:]
