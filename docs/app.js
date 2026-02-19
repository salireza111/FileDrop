const codeLines = [
  "server.listen(8800) -> ready",
  "client.join(" + "'Studio Mac'" + ")",
  "qr.generate(" + "'192.168.0.5'" + ")",
  "drop.enqueue(" + "'shots.zip'" + ")",
  "progress.update(0.82)",
  "note.push(" + "'Assets in /Exports'" + ")",
  "client.send(" + "'iPad Pro'" + ")",
  "transfer.complete(" + "'boards.pdf'" + ")",
  "watcher.sync(" + "'/drops'" + ")",
  "session.keepAlive()"
];

const codeSlots = document.querySelectorAll("[data-code-line]");
let codeIndex = 0;

function updateCodeLines() {
  codeSlots.forEach((slot, i) => {
    const line = codeLines[(codeIndex + i) % codeLines.length];
    slot.textContent = line;
  });
  codeIndex = (codeIndex + 1) % codeLines.length;
}

updateCodeLines();
setInterval(updateCodeLines, 2200);

const navToggle = document.querySelector(".nav-toggle");
const nav = document.querySelector(".nav");

if (navToggle && nav) {
  navToggle.addEventListener("click", () => {
    nav.classList.toggle("nav-open");
  });

  document.querySelectorAll(".nav-links a").forEach((link) => {
    link.addEventListener("click", () => {
      nav.classList.remove("nav-open");
    });
  });
}

document.querySelectorAll("[data-copy-button]").forEach((button) => {
  button.addEventListener("click", () => {
    const address = button.parentElement?.querySelector("[data-copy]");
    if (!address) return;
    const value = address.getAttribute("data-copy") || address.textContent || "";
    if (!value) return;

    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(value.trim()).then(() => {
        button.textContent = "Copied";
        setTimeout(() => {
          button.textContent = "Copy address";
        }, 1200);
      });
    } else {
      const range = document.createRange();
      range.selectNodeContents(address);
      const selection = window.getSelection();
      if (selection) {
        selection.removeAllRanges();
        selection.addRange(range);
      }
      button.textContent = "Selected";
      setTimeout(() => {
        button.textContent = "Copy address";
      }, 1200);
    }
  });
});
