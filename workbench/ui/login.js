(() => {
  const form = document.getElementById("login-form");
  const user = document.getElementById("username");
  const pass = document.getElementById("password");
  const err = document.getElementById("login-error");
  const submit = document.getElementById("submit");
  const eye = document.getElementById("toggle-password");
  const next = new URLSearchParams(location.search).get("next") || "/";

  eye.addEventListener("click", () => {
    const show = pass.type === "password";
    pass.type = show ? "text" : "password";
    eye.setAttribute("aria-label", show ? "隐藏密码" : "显示密码");
    pass.focus();
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    err.textContent = "";
    if (!user.value.trim() || !pass.value) {
      err.textContent = "请输入账号和密码";
      return;
    }
    submit.disabled = true;
    submit.querySelector("span").textContent = "正在验证…";
    try {
      const response = await fetch("/api/login", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: user.value.trim(), password: pass.value, next }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.ok) {
        throw new Error(data.error || "账号或密码不正确");
      }
      location.replace(data.redirect || "/");
    } catch (error) {
      err.textContent = error.message || "登录失败，请稍后重试";
      submit.disabled = false;
      submit.querySelector("span").textContent = "进入系统";
      pass.select();
    }
  });
})();
