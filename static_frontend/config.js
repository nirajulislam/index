const API_BASE_URL = '';

function showNotification(message, isError = false) {
    const n = document.getElementById('notification');
    if (!n) return;
    n.textContent = message;
    n.className = isError ? 'error' : 'success';
    n.style.display = 'block';
    n.style.backgroundColor = isError ? '#e50914' : '#28a745';
    setTimeout(() => n.style.display = 'none', 3000);
}

async function fetchWithAuth(url, options = {}) {
    const token = localStorage.getItem('authToken');
    const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }
    const r = await fetch(url, {
        ...options,
        headers: headers
    });
    return r;
}

async function verifyAuth() {
    return true;
}
