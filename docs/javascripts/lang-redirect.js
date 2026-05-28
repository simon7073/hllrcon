/**
 * 语言自动重定向脚本
 *
 * 优先级：
 * 1. 浏览器/系统默认语言（navigator.language）
 * 2. 英文（en）
 * 3. 中文（zh）
 */
(function () {
  const supported = ["en", "zh"];
  const defaultLang = "en";
  const cookieKey = "mkdocs-i18n-lang";

  function getCookie(name) {
    const match = document.cookie.match(new RegExp("(^| )" + name + "=([^;]+)"));
    return match ? match[2] : null;
  }

  function setCookie(name, value, days) {
    const expires = new Date(Date.now() + days * 86400000).toUTCString();
    document.cookie = name + "=" + value + "; path=/; expires=" + expires;
  }

  // 已手动切换过语言则不再重定向
  if (getCookie(cookieKey)) {
    return;
  }

  const browserLang = (navigator.language || navigator.userLanguage || "")
    .toLowerCase()
    .split("-")[0];

  let targetLang = defaultLang;
  if (supported.includes(browserLang)) {
    targetLang = browserLang;
  }

  const currentPath = window.location.pathname;
  const pathParts = currentPath.split("/").filter(Boolean);

  // 如果已经在目标语言路径下则跳过
  if (pathParts.length > 0 && pathParts[0] === targetLang) {
    return;
  }

  // 构建目标 URL（保持子路径不变）
  const basePath = "/hllrcon/";
  let newPath = basePath + targetLang + "/";

  if (pathParts.length > 1) {
    newPath += pathParts.slice(1).join("/");
  }

  // 保留 query string 和 hash
  newPath += window.location.search + window.location.hash;

  if (newPath !== currentPath) {
    // 记录已自动跳转，避免循环
    setCookie(cookieKey, targetLang, 1);
    window.location.replace(newPath);
  }
})();
