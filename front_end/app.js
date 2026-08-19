const pdfInput = document.getElementById("pdf-input");
const outputName = document.getElementById("output-name");
const watermarkText = document.getElementById("watermark-text");
const startBtn = document.getElementById("start-btn");
const status = document.getElementById("status");
const resultArea = document.getElementById("result-area");

let currentFileId = null;

function setStatus(msg) {
  status.textContent = msg;
}

pdfInput.addEventListener("change", async () => {
  const file = pdfInput.files[0];
  resultArea.innerHTML = "";
  currentFileId = null;
  outputName.disabled = true;
  startBtn.disabled = true;

  if (!file) {
    setStatus("");
    return;
  }

  setStatus("上傳中...");
  const formData = new FormData();
  formData.append("pdf", file);

  try {
    const res = await fetch("/api/upload", { method: "POST", body: formData });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "上傳失敗");

    currentFileId = data.file_id;
    outputName.value = `${data.stem}_wm`;
    outputName.disabled = false;
    startBtn.disabled = false;
    setStatus("");
  } catch (err) {
    setStatus(err.message);
  }
});

startBtn.addEventListener("click", async () => {
  if (!currentFileId) return;

  resultArea.innerHTML = "";
  setStatus("");
  startBtn.disabled = true;
  const originalLabel = startBtn.textContent;
  startBtn.textContent = "處理中...";

  try {
    const res = await fetch("/api/watermark", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        file_id: currentFileId,
        output_name: outputName.value,
        text: watermarkText.value,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "處理失敗");

    const link = document.createElement("a");
    link.href = data.download_url;
    link.textContent = `下載 ${data.download_name}`;
    resultArea.appendChild(link);
  } catch (err) {
    setStatus(err.message);
  } finally {
    startBtn.disabled = false;
    startBtn.textContent = originalLabel;
  }
});
