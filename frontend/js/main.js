// --- KONFIGURACJA ---
const API_URL = '/api/verify';  // Adres Twojego serwera Flask
const SCANNER_ID = 'qr-reader';
let scanner = null; // Zmienna globalna przechowująca instancję skanera

// --- FUNKCJE POMOCNICZE ---

// Aktualizacja paska statusu
function updateStatus(message, type) {
    const statusEl = document.getElementById('status');
    statusEl.innerText = message;
    statusEl.className = type; // klasy: info, success, error, processing
}

// Funkcja robiąca zdjęcie z elementu <video> skanera
function captureImageFromVideo() {
    // 1. Znajdujemy element wideo wewnątrz biblioteki html5-qrcode
    const videoElement = document.querySelector(`#${SCANNER_ID} video`);

    if (!videoElement) {
        throw new Error("Nie znaleziono strumienia wideo.");
    }

    // 2. Tworzymy wirtualne płótno (canvas)
    const canvas = document.createElement("canvas");
    canvas.width = videoElement.videoWidth;
    canvas.height = videoElement.videoHeight;

    // 3. Rysujemy aktualną klatkę wideo na płótnie
    const ctx = canvas.getContext("2d");
    ctx.drawImage(videoElement, 0, 0, canvas.width, canvas.height);

    // 4. Zamieniamy na format Base64 (JPG jakość 80%)
    return canvas.toDataURL("image/jpeg", 0.8);
}

// --- GŁÓWNA LOGIKA ---

// Funkcja obsługująca proces po wykryciu kodu
async function handleScanSuccess(decodedText, decodedResult) {
    // A. Zatrzymujemy obraz (PAUZA), żeby użytkownik wiedział, że skanowanie się udało
    // i żeby zdjęcie nie było rozmazane.
    if (scanner) {
        scanner.pause();
    }

    updateStatus("Kod QR przyjęty. Weryfikacja twarzy...", "processing");

    try {
        // B. Pobieramy zdjęcie z zamrożonego wideo
        const imageBase64 = captureImageFromVideo();

        // C. Wysyłamy dane do serwera (Backend Python)
        const response = await fetch(API_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                qr_code: decodedText,
                image: imageBase64
            })
        });

        const result = await response.json();

        // D. Obsługa odpowiedzi
        if (result.status === 'granted') {
            const userName = result.user_name || "Pracowniku";
            updateStatus(`SUKCES! Witaj, ${userName}.`, "success");
        } else {
            updateStatus(`ODMOWA: ${result.message || "Nie rozpoznano twarzy"}`, "error");
        }

    } catch (err) {
        console.error(err);
        updateStatus("Błąd połączenia z serwerem.", "error");
    }

    // E. Restart skanera po 4 sekundach (aby można było zeskanować kolejną osobę)
    setTimeout(() => {
        if (scanner) {
            scanner.resume(); // Wznawia podgląd z kamery
            updateStatus("Gotowy do skanowania...", "info");
        }
    }, 4000);
}

// --- INICJALIZACJA ---

document.addEventListener('DOMContentLoaded', () => {
    // Tworzymy instancję skanera z domyślnym UI
    scanner = new Html5QrcodeScanner(
        SCANNER_ID,
        {
            fps: 10,                 // Klatki na sekundę
            qrbox: { width: 250, height: 250 }, // Obszar skanowania
            aspectRatio: 1.0,
            showTorchButtonIfSupported: true
        },
        /* verbose= */ false
    );

    // Uruchamiamy renderowanie
    scanner.render(handleScanSuccess, (errorMessage) => {
        // Callback błędów skanowania (wywoływany ciągle, gdy nie widzi kodu)
        // Ignorujemy go, żeby nie zaśmiecać konsoli
    });
});