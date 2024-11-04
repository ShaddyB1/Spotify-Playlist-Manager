// Toast Notification System
const toast = {
    show(message, type = 'success') {
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.textContent = message;
        document.body.appendChild(toast);

        setTimeout(() => {
            toast.style.opacity = '0';
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }
};

// Loading State Management
const loading = {
    show() {
        const overlay = document.createElement('div');
        overlay.className = 'loading-overlay';
        overlay.innerHTML = `
            <div class="loading-spinner"></div>
            <p>Loading...</p>
        `;
        document.body.appendChild(overlay);
    },

    hide() {
        const overlay = document.querySelector('.loading-overlay');
        if (overlay) overlay.remove();
    }
};

// Form Validation
function validateForm(formElement) {
    const requiredFields = formElement.querySelectorAll('[required]');
    let isValid = true;

    requiredFields.forEach(field => {
        if (!field.value.trim()) {
            isValid = false;
            field.classList.add('error');
        } else {
            field.classList.remove('error');
        }
    });

    return isValid;
}

// Debounce Function
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Image Loading with Fallback
function handleImageError(img) {
    img.onerror = null;
    img.src = '/static/img/default-playlist.png';
}

// Theme Toggle
function toggleTheme() {
    const html = document.documentElement;
    const isDark = html.classList.contains('dark');
    
    html.classList.toggle('dark');
    localStorage.setItem('theme', isDark ? 'light' : 'dark');
}

// Initialize Theme
function initializeTheme() {
    const theme = localStorage.getItem('theme') || 
                 (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    
    document.documentElement.classList.toggle('dark', theme === 'dark');
}

// Playlist Search and Filter
const playlistSearch = debounce((searchTerm) => {
    const playlists = document.querySelectorAll('.playlist-card');
    const normalizedTerm = searchTerm.toLowerCase();

    playlists.forEach(playlist => {
        const title = playlist.querySelector('.playlist-title').textContent.toLowerCase();
        playlist.style.display = title.includes(normalizedTerm) ? 'block' : 'none';
    });
}, 300);

// Initialize on Load
document.addEventListener('DOMContentLoaded', () => {
    initializeTheme();
    
    // Handle form submissions
    document.querySelectorAll('form').forEach(form => {
        form.addEventListener('submit', (e) => {
            if (!validateForm(form)) {
                e.preventDefault();
                toast.show('Please fill in all required fields', 'error');
            }
        });
    });

    // Handle image errors
    document.querySelectorAll('img').forEach(img => {
        img.addEventListener('error', () => handleImageError(img));
    });
});