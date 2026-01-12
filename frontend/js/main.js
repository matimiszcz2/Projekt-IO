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
            //
            if (!resultFace.is_admin) {
                scanner.pause();
                setTimeout(() => resetScanner(), 3000);
            }
            // 🔹 POKAŻ MODAL
           // if (!resultFace.is_admin) setTimeout(() => resetScanner(), 3000);
;
            if (resultFace.is_admin) {
                scanner.pause();
                showAccessModal(resultFace.user_name);
            }
                
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

function showAccessModal(userName) {
    document.getElementById("modalMessage").innerText =
        "Witaj " + userName + "!";

    const modalElement = document.getElementById("accessModal");
    const modal = new bootstrap.Modal(modalElement, {
        backdrop: "static",   // nie zamyka kliknięciem tła
        keyboard: false       // nie zamyka ESC
    });

    modal.show();

    // TAK → admin
    document.getElementById("goAdminBtn").onclick = function () {
        window.location.href = "/admin";
    };

    // NIE → zamknij modal + reset skanera
    modalElement.addEventListener("hidden.bs.modal", () => {
        resetScanner();
    }, { once: true });
}
document.addEventListener("DOMContentLoaded", () => {
    const rejectBtn = document.getElementById("reject-btn");
    console.log("Przycisk reject-btn:", rejectBtn);

    if (!rejectBtn) return; // brak przycisku → nic nie robimy

    rejectBtn.addEventListener("click", () => {
        fetch("/admin/reject", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            }
        })
        .then(res => res.json())
        .then(data => {
            /*alert("Uprawnienia admina cofnięte!"); */
            window.location.href = "/";
        })
        .catch(err => console.error(err));
    });
});

document.addEventListener("DOMContentLoaded", () => {

    /* =========================
       MODAL: DODAJ UŻYTKOWNIKA
       ========================= */

    const addUserBtn = document.getElementById("addUserBtn");
    const addUserModalEl = document.getElementById("addUserModal");
    const addUserModal = new bootstrap.Modal(addUserModalEl);

    const saveUserBtn = document.getElementById("saveUserBtn");

    addUserBtn.addEventListener("click", () => {
        addUserModal.show();
    });

    saveUserBtn.addEventListener("click", () => {
    const imie = document.getElementById("addImie").value.trim();
    const nazwisko = document.getElementById("addNazwisko").value.trim();
    const stanowisko = document.getElementById("addStanowisko").value.trim();
    const isAdmin = document.getElementById("addIsAdmin").checked;

    if (!imie || !nazwisko || !stanowisko) {
        alert("Uzupełnij wszystkie pola");
        return;
    }

    fetch("/admin/users/add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            imie,
            nazwisko,
            stanowisko,
            is_admin: isAdmin
        })
    })
    .then(res => res.json())
    .then(data => {
        if (data.status === "ok") {
            addUserModal.hide();     // ✅ ZAMYKA MODAL
            location.reload();      // ✅ ODŚWIEŻA LISTĘ
        } else {
            alert(data.message || "Błąd dodawania użytkownika");
        }
    })
    .catch(err => {
        console.error(err);
        alert("Błąd serwera");
    });
});



    /* =========================
       MODAL: ZARZĄDZAJ UŻYTKOWNIKIEM
       ========================= */

    const manageModalEl = document.getElementById("manageModal");
    const manageModal = new bootstrap.Modal(manageModalEl);

    const modalUserName = document.getElementById("modalUserName");
    const toggleAdminBtn = document.getElementById("toggleAdminBtn");
    const deleteUserBtn = document.getElementById("deleteUserBtn");
    const deactivateEmployeeBtn = document.getElementById("deactivateEmployeeBtn");
    let selectedUserId = null;
    let selectedUserIsAdmin = false;
    let selectedUserIsActive = false;

    document.querySelectorAll(".manage-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            selectedUserId = btn.dataset.id;
            selectedUserIsAdmin = btn.dataset.admin === "true";
            selectedUserIsActive = btn.dataset.active === "true";



            modalUserName.textContent = btn.dataset.name;
            
            deactivateEmployeeBtn.textContent = selectedUserIsActive
                ? "Dezaktywuj"
                : "Aktywuj";
           
            toggleAdminBtn.textContent = selectedUserIsAdmin
                ? "Odbierz uprawnienia admina"
                : "Nadaj uprawnienia admina";
            deleteUserBtn.textContent = "Usuń użytkownika";
    
            manageModal.show();
        });
    });

    toggleAdminBtn.addEventListener("click", () => {
        fetch("/admin/users/toggle-admin", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                user_id: selectedUserId
            })
        })
        .then(res => res.json())
        .then(data => {
            if (data.message) {
                // wszystko ok, reload lub toast
                //alert(data.message);
                location.reload();
            } else {
                alert("Błąd operacji");
            }
        })
        .catch(err => console.error(err));
    });

     deactivateEmployeeBtn.addEventListener("click", () => {
        fetch("/admin/users/deactivate-employee", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ user_id: selectedUserId })
            })
            .then(res => res.json())
            .then(data => {
                if (data.status === "ok") {
                     selectedUserIsActive = data.is_active;
                    // Zmien tekst przycisku w locie
                    
                    //document.querySelector(`.manage-btn[data-id="${selectedUserId}"]`).dataset.active = selectedUserIsActive;

                    location.reload();
                    manageModal.hide();
                    //alert("uzytkownik zdeaktywowany");
                }
            });

   });

     deleteUserBtn.addEventListener("click", () => {
        fetch("/admin/users/delete", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                user_id: selectedUserId
            })
        })
        .then(res => res.json())
        .then(data => {
            if (data.message) {
                // wszystko ok, reload lub toast
                //alert(data.message);
                location.reload();
            } else {
                alert("Błąd operacji");
            }
        })
        .catch(err => console.error(err));
    });

    // zarządzanie i pobieranie qr
    const downloadQrBtn = document.getElementById("downloadQrBtn");
    const regenerateQrBtn = document.getElementById("regenerateQrBtn");

    if (downloadQrBtn && regenerateQrBtn) {

        downloadQrBtn.textContent="Pobierz  QR";
        regenerateQrBtn.textContent="Wygeneruj nowy QR";
        downloadQrBtn.addEventListener("click", () => {
            window.location.href = `/admin/users/qr/${selectedUserId}`;
            manageModal.hide();
        });

        regenerateQrBtn.addEventListener("click", () => {
            fetch("/admin/users/regenerate-qr", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ user_id: selectedUserId })
            })
            .then(res => res.json())
            .then(data => {
                if (data.status === "ok") {
                    manageModal.hide();
                    //alert("Nowy QR wygenerowany");
                }
            });
        });

    }
    // wgrywanie zdjecia wzorcowego
    const uploadFaceBtn = document.getElementById("uploadFaceBtn");
    const faceInput = document.getElementById("faceUploadInput");

    uploadFaceBtn.textContent="Wgraj zdjęcie wzorcowe";
    uploadFaceBtn.addEventListener("click", () => {
    faceInput.value = ""; // reset input
    faceInput.click();    // otwiera okno wyboru pliku
});

// Event change → wysyłka od razu po wybraniu pliku
faceInput.addEventListener("change", () => {
    if (!faceInput.files.length) return; // nic nie wybrano

    const formData = new FormData();
    formData.append("photo", faceInput.files[0]);
    formData.append("user_id", selectedUserId);

    fetch("/admin/users/upload-face", {
        method: "POST",
        body: formData
    })
    .then(res => res.json())
    .then(data => {
        if (data.status === "ok") {
            //alert("Zdjęcie zapisane"); // możesz też toast
            manageModal.hide();        // zamyka modal
        } else {
            alert(data.message || "Błąd uploadu");
        }
        faceInput.value = "";          // reset input
    })
    .catch(err => console.error(err));
});

    const searchInput = document.getElementById("searchInput");
    const table = document.querySelector("table tbody");
    const rows = table.querySelectorAll("tr");

    searchInput.addEventListener("input", () => {
        const query = searchInput.value.toLowerCase();

        rows.forEach(row => {
            // Pobieramy tekst ze wszystkich komórek poza ostatnią (Akcje)
            const cells = Array.from(row.querySelectorAll("td")).slice(0, -1);
            const rowText = cells.map(cell => cell.textContent.toLowerCase()).join(" ");

            if (rowText.includes(query)) {
                row.style.display = ""; // pokaż wiersz
            } else {
                row.style.display = "none"; // ukryj wiersz
            }
        });
    });    
   
   
    


});







document.addEventListener('DOMContentLoaded', () => {
    scanner = new Html5QrcodeScanner(
        SCANNER_ID,
        { fps: 10, qrbox: { width: 250, height: 250 }, aspectRatio: 1.0 },
        false
    );
    scanner.render(handleScanSuccess, (er) => { });
});