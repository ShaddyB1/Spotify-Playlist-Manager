// Toast Notification System
const toast = {
    show(message, type = 'success', duration = 3000) {
        // Remove any existing toasts
        const existingToasts = document.querySelectorAll('.toast');
        existingToasts.forEach(t => t.remove());
        
        // Create toast element
        const toastEl = document.createElement('div');
        toastEl.className = `toast ${type}`;
        
        // Add icon based on type
        let icon = '';
        if (type === 'success') {
            icon = '<svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" /></svg>';
        } else if (type === 'error') {
            icon = '<svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>';
        } else if (type === 'warning') {
            icon = '<svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" /></svg>';
        }
        
        toastEl.innerHTML = `${icon}<span>${message}</span>`;
        document.body.appendChild(toastEl);

        // Animate in
        setTimeout(() => {
            toastEl.style.opacity = '1';
        }, 10);

        // Animate out and remove
        setTimeout(() => {
            toastEl.style.opacity = '0';
            setTimeout(() => toastEl.remove(), 300);
        }, duration);
    }
};

// Loading State Management
const loading = {
    show(message = 'Loading...') {
        // Remove any existing overlay
        this.hide();
        
        const overlay = document.createElement('div');
        overlay.className = 'loading-overlay';
        overlay.innerHTML = `
            <div class="loading-spinner"></div>
            <p>${message}</p>
        `;
        document.body.appendChild(overlay);
        document.body.style.overflow = 'hidden';
    },

    hide() {
        const overlay = document.querySelector('.loading-overlay');
        if (overlay) {
            overlay.remove();
            document.body.style.overflow = '';
        }
    }
};

// Form Validation
function validateForm(formElement) {
    const requiredFields = formElement.querySelectorAll('[required]');
    let isValid = true;
    let firstInvalidField = null;

    requiredFields.forEach(field => {
        if (!field.value.trim()) {
            isValid = false;
            field.classList.add('error');
            
            // Add error message if not already present
            const errorId = `error-${field.id || Math.random().toString(36).substr(2, 9)}`;
            if (!document.getElementById(errorId)) {
                const errorMsg = document.createElement('p');
                errorMsg.id = errorId;
                errorMsg.className = 'text-red-500 text-sm mt-1';
                errorMsg.textContent = field.dataset.errorMsg || 'This field is required';
                field.parentNode.appendChild(errorMsg);
            }
            
            if (!firstInvalidField) firstInvalidField = field;
        } else {
            field.classList.remove('error');
            const errorId = `error-${field.id || ''}`;
            const errorMsg = document.getElementById(errorId);
            if (errorMsg) errorMsg.remove();
        }
    });

    // Focus the first invalid field
    if (firstInvalidField) {
        firstInvalidField.focus();
    }

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
    img.classList.add('fallback-image');
}

// Theme Toggle
function toggleTheme() {
    const html = document.documentElement;
    const isDark = html.classList.contains('dark');
    
    html.classList.toggle('dark');
    localStorage.setItem('theme', isDark ? 'light' : 'dark');
    
    // Update theme toggle button icon
    updateThemeToggleIcon();
}

// Update theme toggle button icon
function updateThemeToggleIcon() {
    const themeToggleButtons = document.querySelectorAll('.theme-toggle');
    const isDark = document.documentElement.classList.contains('dark');
    
    themeToggleButtons.forEach(button => {
        button.innerHTML = isDark 
            ? '<svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" /></svg>'
            : '<svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" /></svg>';
    });
}

// Initialize Theme
function initializeTheme() {
    const theme = localStorage.getItem('theme') || 
                 (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    
    document.documentElement.classList.toggle('dark', theme === 'dark');
    updateThemeToggleIcon();
}

// Playlist Search and Filter
const playlistSearch = debounce((searchTerm) => {
    const playlists = document.querySelectorAll('.playlist-card');
    const emptyState = document.getElementById('emptyState');
    const normalizedTerm = searchTerm.toLowerCase();
    let visibleCount = 0;

    playlists.forEach(playlist => {
        const title = playlist.querySelector('.playlist-title').textContent.toLowerCase();
        const isVisible = title.includes(normalizedTerm);
        playlist.style.display = isVisible ? 'block' : 'none';
        if (isVisible) visibleCount++;
    });
    
    // Show/hide empty state
    if (emptyState) {
        emptyState.style.display = visibleCount === 0 ? 'block' : 'none';
    }
}, 300);

// Sort Playlists
function sortPlaylists(sortBy) {
    const playlistsGrid = document.getElementById('playlistsGrid');
    if (!playlistsGrid) return;
    
    const playlists = Array.from(playlistsGrid.querySelectorAll('.playlist-card'));
    
    playlists.sort((a, b) => {
        if (sortBy === 'name') {
            const nameA = a.querySelector('.playlist-title').textContent.toLowerCase();
            const nameB = b.querySelector('.playlist-title').textContent.toLowerCase();
            return nameA.localeCompare(nameB);
        } else if (sortBy === 'tracks') {
            const tracksA = parseInt(a.dataset.tracks || '0');
            const tracksB = parseInt(b.dataset.tracks || '0');
            return tracksB - tracksA; // Descending order
        } else if (sortBy === 'recent') {
            // Assuming there's a data attribute for date
            const dateA = a.dataset.date || '';
            const dateB = b.dataset.date || '';
            return dateB.localeCompare(dateA); // Descending order
        }
        return 0;
    });
    
    // Re-append in sorted order
    playlists.forEach(playlist => {
        playlistsGrid.appendChild(playlist);
    });
}

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
    
    // Setup theme toggle buttons
    document.querySelectorAll('.theme-toggle').forEach(button => {
        button.addEventListener('click', toggleTheme);
    });
    
    // Setup search functionality
    const searchInput = document.getElementById('searchPlaylists');
    if (searchInput) {
        searchInput.addEventListener('input', (e) => playlistSearch(e.target.value));
    }
    
    // Setup sort functionality
    const sortSelect = document.getElementById('sortPlaylists');
    if (sortSelect) {
        sortSelect.addEventListener('change', (e) => sortPlaylists(e.target.value));
    }
});