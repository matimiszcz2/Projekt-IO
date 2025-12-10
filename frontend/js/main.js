// --- KONFIGURACJA ---
const API_QR_URL = '/api/check-qr';
const API_FACE_URL = '/api/verify-face';
const SCANNER_ID = 'qr-reader';

let scanner = null;
let isProcessing = false;

function updateStatus(message, type) {
    const statusEl = document.getElementById('status');
    statusEl.innerText = message;
    statusEl.className = type;
}

function captureImageFromVideo() {
    const videoElement = document.querySelector(`#${SCANNER_ID} video`);
    if (!videoElement) throw new Error("Brak wideo.");

    const canvas = document.createElement("canvas");
    canvas.width = videoElement.videoWidth;
    canvas.height = videoElement.videoHeight;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(videoElement, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL("image/jpeg", 0.85); // Jakość 85%
}

async function handleScanSuccess(decodedText, decodedResult) {
    if (isProcessing) return;
    isProcessing = true;

    try {
        // --- ETAP 1: ZDJĘCIE KODU QR ---
        updateStatus("Wykryto kod. Przetwarzanie...", "processing");

        // 1. Robimy zdjęcie MOMENTALNIE po wykryciu kodu (na zdjęciu będzie widać kod QR)
        const qrImageBase64 = captureImageFromVideo();

        // 2. Wysyłamy kod + zdjęcie kodu do sprawdzenia
        const responseQr = await fetch(API_QR_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                qr_code: decodedText,
                image_qr: qrImageBase64
            })
        });

        const resultQr = await responseQr.json();

        if (resultQr.status !== 'valid') {
            throw new Error(resultQr.message);
        }

        // --- ETAP 2: ZDJĘCIE TWARZY ---

        // 3. Dajemy użytkownikowi czas na zabranie kodu i ustawienie twarzy
        updateStatus("Kod OK. SPÓJRZ W KAMERĘ!", "info");

        // Czekamy 2 sekundy (możesz zmienić czas tutaj)
        await new Promise(r => setTimeout(r, 2000));

        // 4. Robimy DRUGIE zdjęcie (teraz powinna być sama twarz)
        updateStatus("Weryfikacja twarzy...", "processing");
        const faceImageBase64 = captureImageFromVideo();

        // 5. Wysyłamy do weryfikacji biometrycznej
        const responseFace = await fetch(API_FACE_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                qr_code: decodedText,
                image_face: faceImageBase64
            })
        });

        const resultFace = await responseFace.json();

        if (resultFace.status === 'granted') {
            updateStatus(`OTWARTE: Witaj, ${resultFace.user_name}!`, "success");
            if (scanner) scanner.pause();
            setTimeout(() => resetScanner(), 5000);
        } else {
            throw new Error(resultFace.message || "Twarz nierozpoznana");
        }

    } catch (err) {
        console.error(err);
        updateStatus(`BŁĄD: ${err.message}`, "error");
        setTimeout(() => resetScanner(), 3000);
    }
}

function resetScanner() {
    isProcessing = false;
    updateStatus("Gotowy. Zeskanuj kod QR.", "info");
    if (scanner && scanner.getState() === Html5QrcodeScannerState.PAUSED) {
        scanner.resume();
    }
}

document.addEventListener('DOMContentLoaded', () => {
    scanner = new Html5QrcodeScanner(
        SCANNER_ID,
        { fps: 10, qrbox: { width: 250, height: 250 }, aspectRatio: 1.0 },
        false
    );
    scanner.render(handleScanSuccess, (er) => { });
});