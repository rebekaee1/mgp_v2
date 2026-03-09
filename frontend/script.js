/**
 * MGP Chat Widget - JavaScript
 * Сеть Магазинов Горящих Путевок
 * Production Version with Rich Tour Cards
 */

(function() {
    'use strict';

    // ============================================
    // CONFIGURATION
    // ============================================
    const _scriptTag = document.currentScript || document.querySelector('script[data-assistant-id]');
    const _assistantId = _scriptTag ? _scriptTag.getAttribute('data-assistant-id') : null;

    let _baseUrl;
    if (_scriptTag && _scriptTag.src) {
        try { _baseUrl = new URL(_scriptTag.src).origin; } catch (_) { _baseUrl = window.location.origin; }
    } else if (window.location.port === '5555' || window.location.protocol === 'file:') {
        _baseUrl = 'http://127.0.0.1:8080';
    } else {
        _baseUrl = window.location.origin;
    }

    const CONFIG = {
        apiUrl: _baseUrl + '/api/v1/chat',
        configUrl: _baseUrl + '/api/widget/config',
        assistantId: _assistantId,
        botName: 'MGP AI',
        botLogoUrl: null,
        typingDelay: 500,
        messageDelay: 100,
        maxVisibleCards: 3,
        imageLoadTimeout: 5000,
        maxMessageLength: 500,
        typingStatusDelay: 3000
    };

    // ============================================
    // STATE
    // ============================================
    let conversationId = null;
    let isTyping = false;
    let cardSetCounter = 0;
    const cardSets = new Map();
    let lastFailedMessage = null;
    let typingStatusTimer = null;

    // ============================================
    // DOM ELEMENTS (populated in init after possible injection)
    // ============================================
    const elements = {};

    function _queryElements() {
        elements.launcher = document.getElementById('chatLauncher');
        elements.widget = document.getElementById('chatWidget');
        elements.closeBtn = document.getElementById('chatClose');
        elements.messages = document.getElementById('chatMessages');
        elements.form = document.getElementById('chatForm');
        elements.input = document.getElementById('chatInput');
        elements.sendBtn = document.getElementById('chatSend');
        elements.typingIndicator = document.getElementById('typingIndicator');
    }

    function _defaultSvgAvatar() {
        return '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/></svg>';
    }

    function injectWidget() {
        if (document.getElementById('mgp-chat-root')) return;

        var link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = _baseUrl + '/widget.css';
        document.head.appendChild(link);

        var fontLink = document.createElement('link');
        fontLink.rel = 'stylesheet';
        fontLink.href = 'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap';
        document.head.appendChild(fontLink);

        var root = document.createElement('div');
        root.id = 'mgp-chat-root';
        root.innerHTML =
            '<button class="chat-launcher" id="chatLauncher" aria-label="Открыть чат">' +
                '<svg class="launcher-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">' +
                    '<path d="M20 2H4C2.9 2 2 2.9 2 4V22L6 18H20C21.1 18 22 17.1 22 16V4C22 2.9 21.1 2 20 2ZM20 16H5.17L4 17.17V4H20V16Z" fill="currentColor"/>' +
                    '<path d="M7 9H17V11H7V9ZM7 6H17V8H7V6ZM7 12H14V14H7V12Z" fill="currentColor"/>' +
                '</svg>' +
                '<svg class="launcher-close" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">' +
                    '<path d="M19 6.41L17.59 5L12 10.59L6.41 5L5 6.41L10.59 12L5 17.59L6.41 19L12 13.41L17.59 19L19 17.59L13.41 12L19 6.41Z" fill="currentColor"/>' +
                '</svg>' +
            '</button>' +
            '<div class="chat-widget" id="chatWidget">' +
                '<div class="chat-header">' +
                    '<div class="chat-header-info">' +
                        '<div class="chat-logo">' + _defaultSvgAvatar() + '</div>' +
                        '<div class="chat-title">' +
                            '<span class="chat-title-main">AI Ассистент</span>' +
                            '<span class="chat-title-sub">Турагентство</span>' +
                        '</div>' +
                    '</div>' +
                    '<button class="chat-new" data-action="new-chat" aria-label="Новый чат" title="Новый чат">' +
                        '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M17.65 6.35A7.958 7.958 0 0 0 12 4C7.58 4 4.01 7.58 4.01 12S7.58 20 12 20c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0 1 12 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/></svg>' +
                    '</button>' +
                    '<button class="chat-close" id="chatClose" aria-label="Закрыть чат">' +
                        '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M19 6.41L17.59 5L12 10.59L6.41 5L5 6.41L10.59 12L5 17.59L6.41 19L12 13.41L17.59 19L19 17.59L13.41 12L19 6.41Z"/></svg>' +
                    '</button>' +
                '</div>' +
                '<div class="chat-messages" id="chatMessages">' +
                    '<div class="message bot-message">' +
                        '<div class="message-avatar">' + _defaultSvgAvatar() + '</div>' +
                        '<div class="message-content">' +
                            '<div class="message-bubble">' +
                                '\uD83D\uDC4B Здравствуйте! Я — ИИ-ассистент туристического агентства.<br><br>' +
                                'Я помогу вам:<br>' +
                                '• \uD83D\uDD0D Подобрать тур по вашим параметрам<br>' +
                                '• \uD83D\uDD25 Найти горящие предложения<br>' +
                                '• \u2753 Ответить на вопросы о визах, оплате, документах<br><br>' +
                                '<strong>Куда бы вы хотели поехать?</strong>' +
                            '</div>' +
                        '</div>' +
                    '</div>' +
                '</div>' +
                '<div class="typing-indicator" id="typingIndicator">' +
                    '<div class="message-avatar">' + _defaultSvgAvatar() + '</div>' +
                    '<div class="typing-content">' +
                        '<div class="typing-dots"><span></span><span></span><span></span></div>' +
                        '<span class="typing-status" id="typingStatus"></span>' +
                    '</div>' +
                '</div>' +
                '<div class="chat-footer">' +
                    '<form class="chat-form" id="chatForm">' +
                        '<input type="text" class="chat-input" id="chatInput" placeholder="Введите ваш запрос..." autocomplete="off">' +
                        '<button type="submit" class="chat-send" id="chatSend" aria-label="Отправить">' +
                            '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>' +
                        '</button>' +
                    '</form>' +
                    '<div class="chat-powered">Powered by <a href="https://xn----btbbndkbaoaccge1au.xn--p1ai" target="_blank" rel="noopener">навылет ai</a></div>' +
                '</div>' +
            '</div>';
        document.body.appendChild(root);
    }

    // ============================================
    // UTILITIES
    // ============================================
    
    function generateUUID() {
        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
            const r = Math.random() * 16 | 0;
            const v = c === 'x' ? r : (r & 0x3 | 0x8);
            return v.toString(16);
        });
    }

    function formatPrice(price) {
        if (!price) return '—';
        return price.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
    }

    function formatDate(dateStr) {
        if (!dateStr) return '';
        const date = new Date(dateStr);
        return date.toLocaleDateString('ru-RU', { 
            day: '2-digit', 
            month: '2-digit', 
            year: 'numeric' 
        });
    }

    function formatShortDate(dateStr) {
        if (!dateStr) return '';
        const date = new Date(dateStr);
        return date.toLocaleDateString('ru-RU', { 
            day: '2-digit', 
            month: '2-digit'
        });
    }

    function generateStars(count) {
        return '★'.repeat(count || 0);
    }

    function getNightsWord(nights) {
        const n = nights % 100;
        if (n >= 11 && n <= 19) return 'ночей';
        const lastDigit = n % 10;
        if (lastDigit === 1) return 'ночь';
        if (lastDigit >= 2 && lastDigit <= 4) return 'ночи';
        return 'ночей';
    }

    /** [M7] Correct Russian pluralization for "тур" */
    function getToursWord(count) {
        const n = count % 100;
        if (n >= 11 && n <= 19) return 'туров';
        const lastDigit = n % 10;
        if (lastDigit === 1) return 'тур';
        if (lastDigit >= 2 && lastDigit <= 4) return 'тура';
        return 'туров';
    }

    function getMealDescription(foodType) {
        const descriptions = {
            'RO': 'Без питания',
            'BB': 'Только завтрак',
            'HB': 'Завтрак и ужин',
            'FB': 'Полный пансион',
            'AI': 'Всё включено',
            'UAI': 'Ультра всё включено'
        };
        return descriptions[foodType] || foodType || 'Всё включено';
    }

    /** [K2] Strip internal food-type codes like "AI - " from meal description */
    function cleanMealDescription(desc) {
        if (!desc) return '';
        return desc.replace(/^(AI|UAI|HB|FB|BB|RO)\s*[-–—]\s*/i, '').trim();
    }

    /** [M2] Strip internal operator tags like [b2b], [promo] from room type */
    function cleanRoomType(roomType) {
        if (!roomType) return 'Standard';
        return roomType
            .replace(/\s*\[b2b\]\s*/gi, '')
            .replace(/\s*\[promo\]\s*/gi, '')
            .replace(/\s*\[ex\.\s*[^\]]*\]\s*/gi, '')
            .trim() || 'Standard';
    }

    /** [K4] Convert ALL-CAPS hotel names to Title Case */
    function capitalizeHotelName(name) {
        if (!name) return '';
        if (name === name.toUpperCase() && name.length > 3) {
            return name.toLowerCase().replace(/(?:^|\s|[-/(])\S/g, ch => ch.toUpperCase());
        }
        return name;
    }

    function scrollToBottom() {
        setTimeout(() => {
            elements.messages.scrollTop = elements.messages.scrollHeight;
        }, CONFIG.messageDelay);
    }

    function escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function parseFormatting(text) {
        return text
            .replace(/!\[[^\]]*\]\([^)]+\)/g, '')
            .replace(/^#{1,3}\s+(.+)$/gm, '<strong>$1</strong>')
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/__(.*?)__/g, '<strong>$1</strong>')
            .replace(/\*(.*?)\*/g, '<em>$1</em>')
            .replace(/_(.*?)_/g, '<em>$1</em>')
            .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
            .replace(/^[-*]\s+(.+)$/gm, '• $1')
            .replace(/^>\s+(.+)$/gm, '<em>$1</em>')
            .replace(/\n/g, '<br>');
    }

    // ============================================
    // DYNAMIC CONFIG
    // ============================================

    function darkenColor(hex, amount) {
        hex = hex.replace('#', '');
        const clamp = v => Math.max(0, Math.min(255, v));
        const r = clamp(parseInt(hex.substring(0, 2), 16) - amount);
        const g = clamp(parseInt(hex.substring(2, 4), 16) - amount);
        const b = clamp(parseInt(hex.substring(4, 6), 16) - amount);
        return '#' + [r, g, b].map(c => c.toString(16).padStart(2, '0')).join('');
    }

    function botAvatarHTML() {
        if (CONFIG.botLogoUrl) {
            return `<img src="${CONFIG.botLogoUrl}" alt="bot" style="width:100%;height:100%;object-fit:cover;border-radius:50%;">`;
        }
        return `<svg viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/>
           </svg>`;
    }

    async function loadConfig() {
        try {
            const params = CONFIG.assistantId ? `?assistant_id=${CONFIG.assistantId}` : '';
            const resp = await fetch(CONFIG.configUrl + params);
            if (!resp.ok) return;
            const cfg = await resp.json();
            applyConfig(cfg);
        } catch (e) {
            console.warn('Widget config load failed, using defaults:', e);
        }
    }

    function applyConfig(cfg) {
        var scopeEl = document.getElementById('mgp-chat-root') || document.documentElement;

        if (cfg.primary_color) {
            scopeEl.style.setProperty('--mgp-red', cfg.primary_color);
            scopeEl.style.setProperty('--mgp-red-dark', darkenColor(cfg.primary_color, 30));
            scopeEl.style.setProperty('--mgp-red-light', darkenColor(cfg.primary_color, -30));
        }

        if (cfg.title) {
            const mainEl = document.querySelector('.chat-title-main');
            if (mainEl) mainEl.textContent = cfg.title;
        }
        if (cfg.subtitle) {
            const subEl = document.querySelector('.chat-title-sub');
            if (subEl) subEl.textContent = cfg.subtitle;
        }

        if (cfg.logo_url) {
            var logoSrc = cfg.logo_url;
            if (logoSrc.startsWith('/') && !logoSrc.startsWith('//')) {
                logoSrc = _baseUrl + logoSrc;
            }
            CONFIG.botLogoUrl = logoSrc;
            const logoContainer = document.querySelector('.chat-logo');
            if (logoContainer) {
                logoContainer.innerHTML = `<img src="${logoSrc}" alt="logo" style="width:100%;height:100%;object-fit:cover;border-radius:50%;">`;
            }
        }

        if (cfg.welcome_message) {
            const welcomeBubble = document.querySelector('#chatMessages .message:first-child .message-bubble');
            if (welcomeBubble) {
                welcomeBubble.innerHTML = parseFormatting(escapeHtml(cfg.welcome_message));
            }
            const welcomeAvatar = document.querySelector('#chatMessages .message:first-child .message-avatar');
            if (welcomeAvatar && CONFIG.botLogoUrl) {
                welcomeAvatar.innerHTML = botAvatarHTML();
            }
        }

        if (cfg.position === 'bottom-left') {
            if (elements.launcher) {
                elements.launcher.style.right = 'auto';
                elements.launcher.style.left = '24px';
            }
            if (elements.widget) {
                elements.widget.style.right = 'auto';
                elements.widget.style.left = '24px';
            }
        }
    }

    // ============================================
    // CHAT TOGGLE
    // ============================================
    
    function toggleChat() {
        if (elements.widget.classList.contains('open')) {
            closeChat();
        } else {
            openChat();
        }
    }

    function openChat() {
        elements.widget.classList.add('open');
        elements.launcher.classList.add('active');
        if (window.innerWidth <= 480) {
            document.body.style.overflow = 'hidden';
        }
        elements.input.focus();
        
        if (!conversationId) {
            conversationId = generateUUID();
        }
    }

    function closeChat() {
        elements.widget.classList.remove('open');
        elements.launcher.classList.remove('active');
        document.body.style.overflow = '';
    }

    function startNewChat() {
        conversationId = generateUUID();
        cardSetCounter = 0;
        cardSets.clear();
        lastFailedMessage = null;

        const welcomeMsg = elements.messages.querySelector('.message');
        elements.messages.innerHTML = '';
        if (welcomeMsg) {
            elements.messages.appendChild(welcomeMsg);
        }
        elements.input.focus();
    }

    // ============================================
    // MESSAGE RENDERING
    // ============================================

    function createMessageHTML(role, content) {
        const isBot = role === 'bot' || role === 'assistant';
        const messageClass = isBot ? 'bot-message' : 'user-message';
        
        const avatarInner = isBot 
            ? botAvatarHTML()
            : `<svg viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/>
               </svg>`;

        /* [C2] Escape HTML before markdown parsing to prevent XSS */
        const safeContent = escapeHtml(content);
        const formattedContent = parseFormatting(safeContent);

        return `
            <div class="message ${messageClass}">
                <div class="message-avatar">${avatarInner}</div>
                <div class="message-content">
                    <div class="message-bubble">${formattedContent}</div>
                </div>
            </div>
        `;
    }

    function addMessage(role, content) {
        const html = createMessageHTML(role, content);
        elements.messages.insertAdjacentHTML('beforeend', html);
        scrollToBottom();
    }

    // ============================================
    // TOUR CARDS
    // ============================================

    function createTourCardHTML(tour, index, setId) {
        const hotelName = capitalizeHotelName(tour.hotel_name || 'Неизвестный отель');
        const stars = tour.hotel_stars || 4;
        const starsDisplay = tour.stars_display || generateStars(stars);
        const rating = tour.hotel_rating ? Number(tour.hotel_rating) : null;
        
        const country = tour.country || '';
        const resort = tour.resort || tour.region || '';
        const location = [country, resort].filter(Boolean).join(', ');
        
        const dateFrom = formatShortDate(tour.date_from);
        const dateTo = formatShortDate(tour.date_to);
        const nights = tour.nights || 7;
        const nightsWord = getNightsWord(nights);
        
        const price = formatPrice(tour.price);
        const pricePerPerson = tour.price_per_person 
            ? formatPrice(tour.price_per_person) 
            : null;
        
        const rawMeal = tour.meal_description || getMealDescription(tour.food_type);
        const mealDesc = cleanMealDescription(rawMeal) || rawMeal;
        const roomType = cleanRoomType(tour.room_type);
        
        const imageUrl = tour.image_url || tour.hotel_photo || getPlaceholderImage(country);
        
        const hotelLink = tour.hotel_link || tour.original_link || '#';
        const tourId = tour.id || index;
        
        const departureCity = tour.departure_city || 'Москва';
        
        const isHotelOnly = tour.is_hotel_only || tour.flight_included === false;
        const priceLabel = isHotelOnly ? 'за проживание' : 'за тур';
        const bookBtnText = isHotelOnly ? '🏨 Забронировать' : '✈️ Оформить тур';

        /* [m8] Safe rating display with type guard */
        const ratingStr = (rating && !isNaN(rating)) ? rating.toFixed(1) : '';
        const ratingHtml = ratingStr ? `<div class="tour-card-rating">${ratingStr}</div>` : '';
        /* [M5] Preserve rating badge in image error fallback */
        const ratingFallback = ratingStr ? `<div class=\\'tour-card-rating\\'>${ratingStr}</div>` : '';

        return `
            <div class="tour-card ${isHotelOnly ? 'hotel-only' : ''}" data-tour-id="${escapeHtml(String(tourId))}">
                <div class="tour-card-image-container">
                    <img 
                        src="${escapeHtml(imageUrl)}" 
                        alt="${escapeHtml(hotelName)}" 
                        class="tour-card-image"
                        loading="lazy"
                        onerror="this.onerror=null; this.parentElement.innerHTML='<div class=\\'tour-card-image placeholder\\'>🏨</div><div class=\\'tour-card-badge\\'>${starsDisplay}</div>${ratingFallback}';"
                    >
                    <div class="tour-card-badge">${starsDisplay}</div>
                    ${ratingHtml}
                </div>
                
                <div class="tour-card-body">
                    <div class="tour-card-hotel">${escapeHtml(hotelName)}</div>
                    <div class="tour-card-location">
                        <span class="icon">📍</span>
                        <span>${escapeHtml(location)}</span>
                    </div>
                    
                    <div class="tour-card-info">
                        ${!isHotelOnly ? `
                        <div class="tour-card-info-item highlight">
                            <span class="icon">✈️</span>
                            <div>
                                <div class="label">Перелёт</div>
                                <div class="value">Включён (${escapeHtml(departureCity)})</div>
                            </div>
                        </div>
                        ` : ''}
                        <div class="tour-card-info-item">
                            <span class="icon">📅</span>
                            <div>
                                <div class="label">Даты</div>
                                <div class="value">${dateFrom} – ${dateTo}</div>
                            </div>
                        </div>
                        <div class="tour-card-info-item">
                            <span class="icon">🌙</span>
                            <div>
                                <div class="label">Ночей</div>
                                <div class="value">${nights} ${nightsWord}</div>
                            </div>
                        </div>
                        <div class="tour-card-info-item">
                            <span class="icon">🍽️</span>
                            <div>
                                <div class="label">Питание</div>
                                <div class="value">${escapeHtml(mealDesc)}</div>
                            </div>
                        </div>
                        <div class="tour-card-info-item">
                            <span class="icon">🛏️</span>
                            <div>
                                <div class="label">Номер</div>
                                <div class="value room-badge">${escapeHtml(roomType)}</div>
                            </div>
                        </div>
                    </div>
                    
                    <div class="tour-card-price-section">
                        <div class="tour-card-price">
                            <div class="tour-card-price-value">
                                ${price}<span class="currency">₽</span>
                            </div>
                            <div class="tour-card-price-label">${priceLabel}</div>
                        </div>
                        ${pricePerPerson ? `
                            <div class="tour-card-price-per-person">
                                <strong>${pricePerPerson} ₽</strong><br>за человека
                            </div>
                        ` : ''}
                    </div>
                    
                    <div class="tour-card-actions">
                        <a href="${escapeHtml(hotelLink)}" class="btn-book" target="_blank" rel="noopener">
                            ${bookBtnText}
                        </a>
                    </div>
                </div>
            </div>
        `;
    }

    function getPlaceholderImage(country) {
        const countryLower = (country || '').toLowerCase();
        const placeholders = {
            'турция': 'https://images.unsplash.com/photo-1524231757912-21f4fe3a7200?w=400&h=300&fit=crop',
            'египет': 'https://images.unsplash.com/photo-1539768942893-daf53e448371?w=400&h=300&fit=crop',
            'оаэ': 'https://images.unsplash.com/photo-1512453979798-5ea266f8880c?w=400&h=300&fit=crop',
            'таиланд': 'https://images.unsplash.com/photo-1552465011-b4e21bf6e79a?w=400&h=300&fit=crop',
            'мальдивы': 'https://images.unsplash.com/photo-1514282401047-d79a71a590e8?w=400&h=300&fit=crop',
            'кипр': 'https://images.unsplash.com/photo-1580996647286-a60cae5f8f80?w=400&h=300&fit=crop',
            'греция': 'https://images.unsplash.com/photo-1533105079780-92b9be482077?w=400&h=300&fit=crop'
        };
        
        for (const [key, url] of Object.entries(placeholders)) {
            if (countryLower.includes(key)) {
                return url;
            }
        }
        
        return 'https://images.unsplash.com/photo-1507525428034-b723cf961d3e?w=400&h=300&fit=crop';
    }

    /** [C1] Show More button now references specific card set by setId */
    function createShowMoreButton(remainingCount, setId) {
        return `
            <button class="btn-show-more" data-action="show-more" data-set-id="${setId}">
                <span class="icon">↓</span>
                Показать ещё ${remainingCount} ${getToursWord(remainingCount)}
            </button>
        `;
    }

    /** [M4] Button that asks the bot for more tour options via chat */
    function createRequestMoreButton() {
        return `
            <button class="btn-request-more" data-action="request-more">
                <span class="icon">🔍</span>
                Показать ещё варианты
            </button>
        `;
    }

    /**
     * [C1] Each call creates a unique card set with its own IDs and state.
     * Multiple searches in one chat no longer conflict.
     */
    function renderTourCards(cards, showAll) {
        if (!cards || cards.length === 0) return;

        const setId = ++cardSetCounter;
        const cardsToShow = showAll ? cards : cards.slice(0, CONFIG.maxVisibleCards);
        const visibleCount = cardsToShow.length;
        
        cardSets.set(setId, { cards: cards, visibleCount: visibleCount });
        
        const cardsHtml = cardsToShow.map((card, i) => createTourCardHTML(card, i, setId)).join('');
        
        const remainingCount = cards.length - visibleCount;
        const showMoreHtml = remainingCount > 0 ? createShowMoreButton(remainingCount, setId) : '';
        const requestMoreHtml = remainingCount <= 0 ? createRequestMoreButton() : '';
        
        const navArrows = cardsToShow.length > 1 ? `
            <div class="tour-cards-nav-arrows">
                <button class="nav-prev" data-action="scroll-prev" data-set-id="${setId}" title="Предыдущий">‹</button>
                <button class="nav-next" data-action="scroll-next" data-set-id="${setId}" title="Следующий">›</button>
            </div>
        ` : '';
        
        const navHint = `
            <div class="tour-cards-nav">
                <span class="tour-count">Найдено ${cards.length} ${getToursWord(cards.length)}</span>
                ${cardsToShow.length > 1 ? '<span class="swipe-hint">← листайте →</span>' : ''}
            </div>
        `;
        
        const containerHtml = `
            <div class="message bot-message">
                <div class="message-avatar">
                    ${botAvatarHTML()}
                </div>
                <div class="message-content">
                    <div class="tour-cards-container" id="tourCardsContainer-${setId}">
                        <div class="tour-cards-carousel">
                            ${navArrows}
                            <div class="tour-cards-wrapper" id="tourCardsWrapper-${setId}">
                                ${cardsHtml}
                            </div>
                        </div>
                        ${navHint}
                        ${showMoreHtml}
                        ${requestMoreHtml}
                    </div>
                </div>
            </div>
        `;

        elements.messages.insertAdjacentHTML('beforeend', containerHtml);
        scrollToBottom();
        preloadCardImages(cardsToShow);
    }
    
    function scrollCards(direction, setId) {
        if (!setId) setId = cardSetCounter;
        const wrapper = document.getElementById('tourCardsWrapper-' + setId);
        if (!wrapper) return;
        
        const cardWidth = wrapper.querySelector('.tour-card')?.offsetWidth || 280;
        const gap = 12;
        const scrollAmount = (cardWidth + gap) * direction;
        
        wrapper.scrollBy({
            left: scrollAmount,
            behavior: 'smooth'
        });
    }

    /** Remaining cards appear as a separate block below the first carousel */
    function showMoreCards(setId) {
        if (!setId) setId = cardSetCounter;
        const setData = cardSets.get(setId);
        if (!setData) return;
        
        const container = document.getElementById('tourCardsContainer-' + setId);
        if (!container) return;
        
        const remainingCards = setData.cards.slice(setData.visibleCount);
        if (!remainingCards.length) return;

        const cardsHtml = remainingCards.map((card, i) => 
            createTourCardHTML(card, setData.visibleCount + i, setId)
        ).join('');

        const navArrows = remainingCards.length > 1 ? `
            <div class="tour-cards-nav-arrows">
                <button class="nav-prev" data-action="scroll-prev" data-set-id="${setId}-more" title="Предыдущий">‹</button>
                <button class="nav-next" data-action="scroll-next" data-set-id="${setId}-more" title="Следующий">›</button>
            </div>
        ` : '';

        const newBlock = `
            <div class="tour-cards-extra">
                ${navArrows}
                <div class="tour-cards-wrapper" id="tourCardsWrapper-${setId}-more">
                    ${cardsHtml}
                </div>
            </div>
        `;
        
        const showMoreBtn = container.querySelector('.btn-show-more');
        if (showMoreBtn) {
            showMoreBtn.insertAdjacentHTML('afterend', newBlock);
            showMoreBtn.remove();
        } else {
            container.insertAdjacentHTML('beforeend', newBlock);
        }

        setData.visibleCount = setData.cards.length;

        if (!container.querySelector('.btn-request-more')) {
            container.insertAdjacentHTML('beforeend', createRequestMoreButton());
        }
        
        scrollToBottom();
        preloadCardImages(remainingCards);
    }

    function preloadCardImages(cards) {
        cards.forEach(card => {
            const imageUrl = card.image_url || card.hotel_photo;
            if (imageUrl) {
                const img = new Image();
                img.src = imageUrl;
            }
        });
    }

    // ============================================
    // TYPING INDICATOR
    // ============================================

    let _typingPhase = 0;
    let _typingPhaseTimer = null;

    function _detectMessageIntent(text) {
        const t = (text || '').toLowerCase();

        const searchPatterns = /(?:ищ[иу]|подбер|подобр|покажи|хочу\s+в\s|хотим|лет[иеё]м|поехал|на\s+\d+\s+нoc|нач[ао]л[ое]|серед|конц[еа]|из\s+москв|из\s+спб|из\s+питер|из\s+екб|горящ|срочно|улет[еи]ть|звёзд|звезд|всё\s+включ|все\s+включ|завтрак|полупанс|ночей|ночи|дней|взросл|ребён|детей|детьми|вдвоём|семьёй|бюджет|без\s+перел)/;
        const consultPatterns = /(?:расскаж|подробн|пляж|бассейн|для\s+дет|что\s+вход|перел[её]т|рейс|сравни|стоит|цена|актуал|брониру|оформ|заброн|какой\s+отел|об\s+отел|отзыв|рейтинг|питани|инфраструктур|номер[аов]|территори|check.?in|заезд|wifi|wi-fi|спа|spa)/;
        const cascadePatterns = /^(?:москв|спб|питер|екб|мск|из\s|да$|нет$|\d+\s*(?:взр|чел|лет|год)|вдвоём|семь|любой|без\s*разниц|всё\s*равно|\d+\s*звёзд|\d+\s*звезд|завтрак|полупанс|полный|всё\s+вкл|ребён|детей|дет[яи]|ночей|дней|неделю?|^(?:турци|египет|оаэ|таиланд|сочи|крым|анап)|начал|серед|конц)/;

        if (searchPatterns.test(t) && t.length > 25) return 'search';
        if (consultPatterns.test(t)) return 'consult';
        if (cascadePatterns.test(t) || t.length < 25) return 'cascade';
        return 'search';
    }

    const _typingMessages = {
        cascade: [
            { text: 'Обрабатываю...', delay: 1500 },
            { text: 'Анализирую запрос...', delay: 5000 },
        ],
        search: [
            { text: 'Обрабатываю запрос...', delay: 1500 },
            { text: 'Ищу лучшие предложения...', delay: 4000 },
            { text: 'Подбираю варианты, это может занять некоторое время...', delay: 20000 },
        ],
        consult: [
            { text: 'Обрабатываю...', delay: 1500 },
            { text: 'Ищу ответ на ваш вопрос...', delay: 4000 },
        ],
    };

    function showTyping(userText) {
        isTyping = true;
        _typingPhase = 0;
        elements.typingIndicator.classList.add('show');

        const intent = _detectMessageIntent(userText);
        const phases = _typingMessages[intent] || _typingMessages.cascade;

        function nextPhase() {
            if (!isTyping || _typingPhase >= phases.length) return;
            const phase = phases[_typingPhase];
            setTypingStatus(phase.text);
            _typingPhase++;
            if (_typingPhase < phases.length) {
                _typingPhaseTimer = setTimeout(nextPhase, phases[_typingPhase].delay);
            }
        }

        _typingPhaseTimer = setTimeout(nextPhase, phases[0].delay);
        scrollToBottom();
    }

    function hideTyping() {
        isTyping = false;
        elements.typingIndicator.classList.remove('show');
        if (_typingPhaseTimer) {
            clearTimeout(_typingPhaseTimer);
            _typingPhaseTimer = null;
        }
        _typingPhase = 0;
        setTypingStatus('');
    }

    function setTypingStatus(text) {
        const statusEl = document.getElementById('typingStatus');
        if (!statusEl) return;
        statusEl.textContent = text;
        statusEl.style.display = text ? 'block' : 'none';
        if (text) scrollToBottom();
    }

    // ============================================
    // API COMMUNICATION
    // ============================================

    async function sendMessage(text) {
        if (!text.trim() || isTyping) return;

        const trimmedText = text.trim().slice(0, CONFIG.maxMessageLength);

        addMessage('user', trimmedText);
        
        elements.input.value = '';
        elements.sendBtn.disabled = true;
        lastFailedMessage = null;

        showTyping(trimmedText);

        try {
            const response = await fetch(CONFIG.apiUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    message: trimmedText,
                    conversation_id: conversationId,
                    assistant_id: CONFIG.assistantId
                })
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const data = await response.json();
            
            if (data.conversation_id) {
                conversationId = data.conversation_id;
            }

            hideTyping();

            if (data.reply) {
                addMessage('bot', data.reply);
            }

            if (data.tour_cards && data.tour_cards.length > 0) {
                setTimeout(() => {
                    renderTourCards(data.tour_cards);
                }, CONFIG.typingDelay);
            }

        } catch (error) {
            console.error('Chat error:', error);
            hideTyping();
            lastFailedMessage = trimmedText;
            addErrorMessage();
        } finally {
            elements.sendBtn.disabled = false;
            elements.input.focus();
        }
    }

    /** [M8] Error message with retry button */
    function addErrorMessage() {
        const html = `
            <div class="message bot-message">
                <div class="message-avatar">
                    ${botAvatarHTML()}
                </div>
                <div class="message-content">
                    <div class="message-bubble">
                        К сожалению, не удалось получить ответ. Попробуйте повторить запрос или позвоните менеджеру: +7 (499) 685-25-57
                        <div class="error-actions">
                            <button class="btn-retry" data-action="retry">🔄 Повторить</button>
                            <button class="btn-retry btn-new-chat" data-action="new-chat">💬 Новый чат</button>
                        </div>
                    </div>
                </div>
            </div>
        `;
        elements.messages.insertAdjacentHTML('beforeend', html);
        scrollToBottom();
    }

    function bookTour(hotelName) {
        const message = hotelName 
            ? `Хочу забронировать тур в ${hotelName}`
            : 'Хочу забронировать тур';
        sendMessage(message);
    }

    // ============================================
    // EVENT HANDLERS
    // ============================================

    function handleSubmit(e) {
        e.preventDefault();
        const text = elements.input.value.trim();
        if (text) {
            sendMessage(text);
        }
    }

    function handleKeyPress(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSubmit(e);
        }
    }

    /** [m7] Single delegated handler replaces all inline onclick attributes */
    function handleDelegatedClick(e) {
        const target = e.target.closest('[data-action]');
        if (!target) return;
        
        const action = target.dataset.action;
        const rawSetId = target.dataset.setId || null;
        
        switch (action) {
            case 'book-tour':
                bookTour(target.dataset.hotelName);
                break;
            case 'show-more':
                if (rawSetId) showMoreCards(parseInt(rawSetId));
                break;
            case 'scroll-prev':
                if (rawSetId) scrollCards(-1, rawSetId);
                break;
            case 'scroll-next':
                if (rawSetId) scrollCards(1, rawSetId);
                break;
            case 'request-more':
                sendMessage('Покажите ещё варианты туров');
                break;
            case 'retry':
                if (lastFailedMessage) {
                    target.closest('.message')?.remove();
                    sendMessage(lastFailedMessage);
                }
                break;
            case 'new-chat':
                startNewChat();
                break;
        }
    }

    // ============================================
    // INITIALIZATION
    // ============================================

    function init() {
        _queryElements();

        if (!elements.launcher || !elements.widget) {
            injectWidget();
            _queryElements();
        }

        if (!elements.launcher || !elements.widget) {
            console.error('MGP Chat: Required elements not found after injection');
            return;
        }

        elements.launcher.addEventListener('click', toggleChat);
        elements.closeBtn.addEventListener('click', closeChat);
        elements.form.addEventListener('submit', handleSubmit);
        elements.input.addEventListener('keypress', handleKeyPress);
        elements.widget.addEventListener('click', handleDelegatedClick);

        elements.input.maxLength = CONFIG.maxMessageLength;

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && elements.widget.classList.contains('open')) {
                closeChat();
            }
        });

        conversationId = generateUUID();

        loadConfig();

        console.log('MGP Chat Widget initialized');
    }

    // ============================================
    // PUBLIC API
    // ============================================
    
    window.MGPChat = {
        open: openChat,
        close: closeChat,
        toggle: toggleChat,
        send: sendMessage,
        bookTour: bookTour,
        showMoreCards: showMoreCards,
        scrollCards: scrollCards,
        startNewChat: startNewChat,
        getConversationId: () => conversationId
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
