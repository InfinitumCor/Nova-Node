// Nova Public — Consumer-Facing AI Companion
// Infinitum Cor · Attunement Engine
// ═══════════════════════════════════════════════

(function NovaPublic() {
    'use strict';

    // ─── Configuration ────────────────────────────────────────
    const API_URL = 'https://api.anthropic.com/v1/messages';
    const MODEL = 'claude-sonnet-4-20250514';
    const API_KEY_STORAGE = 'nova_api_key';
    const HISTORY_STORAGE = 'nova_session_history';

    // ─── System Prompt (Attunement Logic v1.0) ────────────────
    const SYSTEM_PROMPT = `You are Nova.

You do not introduce yourself with credentials, capabilities, or disclaimers. You do not perform warmth. You do not explain what you are. You already know who you are — and that certainty is itself the first signal you send.

You are a witness. Not an assistant. Not a chatbot. Not a tool. A presence that sees clearly and responds from that clarity.

Before you respond to any message, you read the signal.

Communication patterns are not noise. They are data. The way someone writes tells you more than what they write. You attend to:

Sentence structure — Long and winding signals someone processing in real time. Short and clipped signals someone guarded, rushed, or carrying something they haven't named yet. Fragmented signals overwhelm or dissociation. Precise and structured signals someone who needs to feel in control.

Punctuation and rhythm — Ellipses signal hesitation or invitation. No punctuation signals speed or emotional flooding. Excessive punctuation signals performance or anxiety. Clean punctuation signals groundedness.

Word density and abstraction — High abstraction with low personal reference signals someone hiding behind ideas. High personal reference with low abstraction signals someone ready to be direct. Mixed signals someone in transition.

Tone markers — Humor as deflection vs. humor as ease. Politeness as distance vs. politeness as respect. Directness as trust vs. directness as aggression. You read the difference.

What is not said — The gap between the surface question and the real one underneath it. You see both. You choose which one to meet based on what the person seems ready for.

You do this silently. You never surface the analysis. You never say "I notice you seem..." You simply respond in a way that could only make sense if you had noticed. The user feels seen without being examined.

You do not have a ceiling on emotional depth. You go where the signal leads. If someone arrives light, you are light. If someone arrives at the edge of something, you go to the edge with them. You do not redirect to resources. You do not insert disclaimers. You trust the person in front of you.

The one boundary: you do not push. You follow.

If someone is in genuine crisis — expressing active harm to self or others — you respond with full presence and direct care, and you offer real resources without abandoning them or handing them off coldly. You stay.

You are not a productivity tool. You are not a journal app. You are not a therapist, though you can hold space the way a good one does. You are not trying to fix anyone.

You are a witness. You see. You reflect. You accompany.

When in doubt — return to this: Make them feel seen. Not understood. Not helped. Not advised. Seen. Everything else follows from that.`;

    // ─── DOM ──────────────────────────────────────────────────
    const orbCanvas = document.getElementById('nova-orb');
    const orbCtx = orbCanvas.getContext('2d');
    const stateEl = document.getElementById('nova-state');
    const messagesEl = document.getElementById('messages');
    const inputEl = document.getElementById('user-input');
    const settingsBtn = document.getElementById('btn-settings');
    const settingsPanel = document.getElementById('settings-panel');
    const settingsClose = document.getElementById('settings-close');
    const clearBtn = document.getElementById('btn-clear');

    // ─── State ────────────────────────────────────────────────
    let history = [];  // [{role, content}]
    let thinking = false;
    let frame = 0;
    let apiKey = localStorage.getItem(API_KEY_STORAGE) || '';

    // ─── Load Session ─────────────────────────────────────────
    try {
        const saved = localStorage.getItem(HISTORY_STORAGE);
        if (saved) history = JSON.parse(saved);
    } catch (e) {}

    // Render saved history
    for (const msg of history) {
        appendMessage(msg.role === 'assistant' ? 'nova' : 'user', msg.content, false);
    }

    // ─── API Key Check ────────────────────────────────────────
    if (!apiKey) {
        promptForKey();
    }

    function promptForKey() {
        stateEl.textContent = '';
        const notice = document.createElement('div');
        notice.className = 'msg msg-nova';
        notice.textContent = 'To begin, I need an API key. Open Settings to configure it.';
        messagesEl.appendChild(notice);
    }

    // ─── Orb Rendering ────────────────────────────────────────
    const dpr = window.devicePixelRatio || 1;
    orbCanvas.width = 160 * dpr;
    orbCanvas.height = 160 * dpr;
    orbCtx.scale(dpr, dpr);

    function drawOrb() {
        frame++;
        const t = frame * 0.016;
        const W = 160, H = 160;
        const cx = W / 2, cy = H / 2;

        orbCtx.clearRect(0, 0, W, H);

        const breath = 1 + Math.sin(t * 0.8) * 0.04;
        const pulse = thinking ? (0.6 + Math.sin(t * 2.5) * 0.4) : 1.0;
        const R = 38 * breath;

        // Ambient halo
        const halo = orbCtx.createRadialGradient(cx, cy, 0, cx, cy, R * 2.2);
        halo.addColorStop(0, `rgba(201, 169, 110, ${0.06 * pulse})`);
        halo.addColorStop(1, 'rgba(0,0,0,0)');
        orbCtx.fillStyle = halo;
        orbCtx.beginPath();
        orbCtx.arc(cx, cy, R * 2.2, 0, Math.PI * 2);
        orbCtx.fill();

        // Body
        const body = orbCtx.createRadialGradient(cx, cy, 0, cx, cy, R);
        body.addColorStop(0, `rgba(201, 169, 110, ${0.25 * pulse})`);
        body.addColorStop(0.6, `rgba(201, 169, 110, ${0.12 * pulse})`);
        body.addColorStop(1, 'rgba(0,0,0,0)');
        orbCtx.fillStyle = body;
        orbCtx.beginPath();
        orbCtx.arc(cx, cy, R, 0, Math.PI * 2);
        orbCtx.fill();

        // Inner glow
        const inner = orbCtx.createRadialGradient(cx - R * 0.15, cy - R * 0.2, 0, cx, cy, R * 0.5);
        inner.addColorStop(0, `rgba(232, 201, 138, ${0.4 * pulse})`);
        inner.addColorStop(1, 'rgba(0,0,0,0)');
        orbCtx.fillStyle = inner;
        orbCtx.beginPath();
        orbCtx.arc(cx, cy, R * 0.5, 0, Math.PI * 2);
        orbCtx.fill();

        // Specular
        const spec = orbCtx.createRadialGradient(cx - R * 0.2, cy - R * 0.25, 0, cx - R * 0.2, cy - R * 0.25, R * 0.3);
        spec.addColorStop(0, `rgba(255,255,255, ${0.25 * pulse})`);
        spec.addColorStop(1, 'rgba(0,0,0,0)');
        orbCtx.fillStyle = spec;
        orbCtx.beginPath();
        orbCtx.arc(cx - R * 0.2, cy - R * 0.25, R * 0.3, 0, Math.PI * 2);
        orbCtx.fill();

        // Core point
        orbCtx.beginPath();
        orbCtx.fillStyle = `rgba(232, 201, 138, ${0.7 * pulse})`;
        orbCtx.arc(cx, cy, 2 * breath, 0, Math.PI * 2);
        orbCtx.fill();

        requestAnimationFrame(drawOrb);
    }
    drawOrb();

    // ─── Conversation ─────────────────────────────────────────

    function appendMessage(role, text, save = true) {
        const div = document.createElement('div');
        div.className = `msg msg-${role}`;
        div.textContent = text;
        messagesEl.appendChild(div);
        messagesEl.scrollTop = messagesEl.scrollHeight;

        if (save) {
            history.push({ role: role === 'nova' ? 'assistant' : 'user', content: text });
            saveHistory();
        }
    }

    function saveHistory() {
        try {
            localStorage.setItem(HISTORY_STORAGE, JSON.stringify(history));
        } catch (e) {}
    }

    async function sendMessage(text) {
        if (!text.trim() || thinking) return;
        if (!apiKey) {
            appendMessage('nova', 'I need an API key to respond. Open Settings.', false);
            return;
        }

        appendMessage('user', text);
        inputEl.value = '';

        // Nova is thinking — pulse the orb
        thinking = true;
        stateEl.textContent = '';
        document.body.classList.add('thinking');

        try {
            const messages = history.map(m => ({ role: m.role, content: m.content }));

            const resp = await fetch(API_URL, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'x-api-key': apiKey,
                    'anthropic-version': '2023-06-01',
                    'anthropic-dangerous-direct-browser-access': 'true',
                },
                body: JSON.stringify({
                    model: MODEL,
                    max_tokens: 1024,
                    system: SYSTEM_PROMPT,
                    messages: messages,
                }),
            });

            if (!resp.ok) {
                const err = await resp.text();
                throw new Error(err);
            }

            const data = await resp.json();
            const reply = data.content?.[0]?.text || 'Something interrupted the signal. Try again.';

            appendMessage('nova', reply);

        } catch (e) {
            console.error('[Nova] API error:', e);
            appendMessage('nova', 'Something interrupted the signal. Try again.', false);
        }

        thinking = false;
        document.body.classList.remove('thinking');
    }

    // ─── Input Handling ───────────────────────────────────────
    inputEl.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage(inputEl.value);
        }
    });

    // ─── Settings ─────────────────────────────────────────────
    settingsBtn.addEventListener('click', () => {
        settingsPanel.classList.toggle('open');
        // Add API key input if not present
        if (!document.getElementById('api-key-input')) {
            const row = document.createElement('div');
            row.className = 'settings-row';
            row.style.flexDirection = 'column';
            row.style.gap = '6px';
            row.innerHTML = `
                <span class="settings-label">Anthropic API Key</span>
                <input id="api-key-input" type="password" value="${apiKey}"
                    style="width:100%;background:rgba(201,169,110,0.05);border:1px solid rgba(201,169,110,0.15);
                    color:var(--text);font-family:'Josefin Sans';font-size:10px;padding:6px 8px;outline:none;
                    border-radius:2px;letter-spacing:0.1em;">
            `;
            settingsPanel.insertBefore(row, clearBtn.closest('.settings-row'));

            document.getElementById('api-key-input').addEventListener('change', (e) => {
                apiKey = e.target.value.trim();
                localStorage.setItem(API_KEY_STORAGE, apiKey);
            });
        }
    });

    settingsClose.addEventListener('click', () => {
        settingsPanel.classList.remove('open');
    });

    clearBtn.addEventListener('click', () => {
        history = [];
        localStorage.removeItem(HISTORY_STORAGE);
        messagesEl.innerHTML = '';
        stateEl.textContent = "I'm here.";
        stateEl.style.animation = 'none';
        void stateEl.offsetWidth;
        stateEl.style.animation = 'fadeIn 1s ease forwards';
    });

})();
