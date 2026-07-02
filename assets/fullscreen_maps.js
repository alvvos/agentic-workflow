document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-fullscreen-for]");
    if (!btn) return;
    var targetId = btn.getAttribute("data-fullscreen-for");
    var el = document.getElementById(targetId);
    if (!el) return;
    if (el.requestFullscreen) el.requestFullscreen();
    else if (el.webkitRequestFullscreen) el.webkitRequestFullscreen();
});
