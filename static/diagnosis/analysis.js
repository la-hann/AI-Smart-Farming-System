const form = document.querySelector("#leaf-analysis");
const photo = document.querySelector("#leaf-photo");
const camera = document.querySelector("#leaf-camera");
const button = form.querySelector("button");
const statusMessage = document.querySelector("#analysis-status");
const result = document.querySelector("#analysis-result");
const resultTitle = document.querySelector("#analysis-title");
const score = document.querySelector("#analysis-score");
const advice = document.querySelector("#analysis-advice");
const source = document.querySelector("#analysis-source");
const sourceRow = document.querySelector("#analysis-source-row");

const size = 224;
const resizeEdge = 256;
const temperature = 0.8845188130635788;
const minimumScore = 0.75;
const maximumFileSize = 12 * 1024 * 1024;
const maize = {
  7: {
    label: "Possible gray leaf spot",
    advice: "Check for rectangular spots bounded by leaf veins. Scout nearby plants and ask your extension officer to confirm. For future seasons, discuss resistant maize varieties and rotation with a non-maize crop.",
    source: "https://extension.umn.edu/agriculture/crop-production/corn/gray-leaf-spot-on-corn",
  },
  8: {
    label: "Possible common rust",
    advice: "Check both sides of leaves for raised rust-coloured pustules. Scout several plants and ask an extension officer to distinguish common rust from other rust diseases. Consider resistant maize varieties for future planting.",
    source: "https://extension.umn.edu/agriculture/crop-production/corn/common-rust-on-corn",
  },
  9: {
    label: "Possible northern leaf blight",
    advice: "Check nearby plants for long, cigar-shaped tan or grey lesions. Ask an extension officer to confirm. Where the disease recurs, consider resistant varieties and rotation away from maize.",
    source: "https://extension.sdstate.edu/northern-corn-leaf-blight-developing-corn",
  },
  10: {
    label: "Leaf appears healthy",
    advice: "Continue checking several plants. If symptoms persist, photograph another affected leaf and consult your extension officer.",
  },
};

let modelPromise;
function loadModel() {
  if (!modelPromise) {
    ort.env.wasm.numThreads = 1;
    const assets = new URL(form.dataset.assets, window.location.href);
    ort.env.wasm.wasmPaths = {
      mjs: new URL("ort-wasm-simd-threaded.js", assets).href,
      wasm: new URL("ort-wasm-simd-threaded.wasm", assets).href,
    };
    modelPromise = ort.InferenceSession.create(form.dataset.assets + "maize-mobilenetv2.onnx", {
      executionProviders: ["wasm"],
    }).catch((error) => {
      modelPromise = undefined;
      throw error;
    });
  }
  return modelPromise;
}

async function imageTensor(file) {
  let image;
  try {
    image = await createImageBitmap(file);
  } catch {
    throw new Error("The photo could not be opened. Try another JPEG, PNG, or WebP file.");
  }
  try {
    const factor = resizeEdge / Math.min(image.width, image.height);
    const width = Math.floor(image.width * factor);
    const height = Math.floor(image.height * factor);
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = size;
    const context = canvas.getContext("2d");
    context.fillStyle = "white";
    context.fillRect(0, 0, size, size);
    context.imageSmoothingQuality = "low";
    context.drawImage(image, -Math.floor((width - size) / 2), -Math.floor((height - size) / 2), width, height);
    const {data} = context.getImageData(0, 0, size, size);
    const pixels = size * size;
    const values = new Float32Array(3 * pixels);
    for (let index = 0; index < pixels; index++) {
      for (let channel = 0; channel < 3; channel++) {
        values[channel * pixels + index] = data[index * 4 + channel] / 127.5 - 1;
      }
    }
    return new ort.Tensor("float32", values, [1, 3, size, size]);
  } finally {
    image.close();
  }
}

function showPrediction(logits) {
  if (logits.length !== 38 || !logits.every(Number.isFinite)) {
    throw new Error("The model did not return a valid result. Try again.");
  }
  const maximum = Math.max(...logits);
  const predictedClass = logits.indexOf(maximum);
  const modelScore = 1 / logits.reduce((sum, value) => sum + Math.exp((value - maximum) / temperature), 0);
  const prediction = modelScore >= minimumScore ? maize[predictedClass] : undefined;
  resultTitle.textContent = prediction ? prediction.label : "Unable to identify a maize leaf condition";
  score.textContent = prediction ? `Model score ${Math.round(modelScore * 100)}%` : "";
  advice.textContent = prediction ? prediction.advice :
    "Try a clear photo of one maize leaf in daylight. If the problem is spreading, ask a local extension officer to inspect the crop.";
  sourceRow.hidden = !prediction?.source;
  if (prediction?.source) source.href = prediction.source;
  result.hidden = false;
}

if (typeof ort === "undefined" || typeof createImageBitmap !== "function") {
  statusMessage.textContent = "The browser could not start leaf analysis. Reload the page or try an updated browser.";
} else {
  button.disabled = false;
}

function selectPhoto(otherInput) {
  otherInput.value = "";
  result.hidden = true;
  statusMessage.textContent = "";
}
photo.addEventListener("change", () => selectPhoto(camera));
camera.addEventListener("change", () => selectPhoto(photo));

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  result.hidden = true;
  const file = camera.files[0] || photo.files[0];
  if (!file || file.size > maximumFileSize) {
    statusMessage.textContent = "Choose a JPEG, PNG, or WebP image smaller than 12 MB.";
    return;
  }

  button.disabled = photo.disabled = camera.disabled = true;
  statusMessage.textContent = "Analysing photo. The first run downloads the model.";
  let input;
  let output;
  try {
    input = await imageTensor(file);
    const model = await loadModel();
    const outputs = await model.run({[model.inputNames[0]]: input});
    output = outputs[model.outputNames[0]];
    showPrediction(output.data);
    statusMessage.textContent = "";
  } catch (error) {
    console.warn("Leaf analysis failed", error);
    statusMessage.textContent = error instanceof Error && error.message.startsWith("The photo") ?
      error.message : "Analysis could not finish. Check your connection and try again.";
  } finally {
    input?.dispose();
    output?.dispose();
    button.disabled = photo.disabled = camera.disabled = false;
  }
});
