/**
 * Motaaked Checkout - Drop-In Modal Widget SDK
 * (c) 2026 Motaaked / InstaTakeed Platform
 * Zero-dependency, responsive modal checkout for any web application or CMS.
 */
(function (global) {
    'use strict';

    // Prevent double instantiation
    if (global.MotaakedCheckout) {
        return;
    }

    // Determine default base URL from the script tag src or window.location
    function detectScriptBaseUrl() {
        if (typeof document !== 'undefined') {
            const scripts = document.getElementsByTagName('script');
            for (let i = 0; i < scripts.length; i++) {
                const src = scripts[i].src || '';
                if (src.indexOf('motaaked-checkout.js') !== -1) {
                    try {
                        const url = new URL(src);
                        return url.origin;
                    } catch (e) {
                        // fallback
                    }
                }
            }
        }
        return (typeof window !== 'undefined' && window.location && window.location.origin) ? window.location.origin : '';
    }

    const defaultBaseUrl = detectScriptBaseUrl();

    let activeModal = null;
    let messageListener = null;
    let keydownListener = null;

    const MotaakedCheckout = {
        version: '1.0.0',

        /**
         * Opens the Drop-In Modal Checkout.
         * @param {Object} options Configuration object:
         *   - sessionToken (string, required): Session token from POST /v1/checkout/session
         *   - checkoutUrl (string, optional): Full hosted checkout URL
         *   - baseUrl (string, optional): Gateway portal base URL
         *   - onSuccess (function): Callback on successful verification ({ order_id, reference_id, amount })
         *   - onCancel (function): Callback when user cancels
         *   - onClose (function): Callback when modal is closed
         *   - onError (function): Callback on error
         */
        open: function (options) {
            options = options || {};

            if (!options.sessionToken && !options.checkoutUrl) {
                console.error('[MotaakedCheckout] Either sessionToken or checkoutUrl must be provided.');
                if (typeof options.onError === 'function') {
                    options.onError(new Error('Missing sessionToken or checkoutUrl'));
                }
                return;
            }

            // Close any open instance first
            this.close();

            const baseUrl = options.baseUrl || defaultBaseUrl;
            let targetUrl = options.checkoutUrl;
            if (!targetUrl) {
                targetUrl = `${baseUrl.replace(/\/$/, '')}/checkout/embed?session=${encodeURIComponent(options.sessionToken)}`;
            }

            // 1. Create Modal Backdrop
            const backdrop = document.createElement('div');
            backdrop.id = 'motaaked-checkout-backdrop';
            backdrop.setAttribute('role', 'dialog');
            backdrop.setAttribute('aria-modal', 'true');
            backdrop.style.cssText = [
                'position: fixed',
                'top: 0',
                'left: 0',
                'width: 100vw',
                'height: 100vh',
                'background-color: rgba(15, 23, 42, 0.82)',
                'backdrop-filter: blur(8px)',
                '-webkit-backdrop-filter: blur(8px)',
                'z-index: 9999999',
                'display: flex',
                'align-items: center',
                'justify-content: center',
                'padding: 16px',
                'box-sizing: border-box',
                'opacity: 0',
                'transition: opacity 0.25s ease-out',
            ].join(';');

            // 2. Create Modal Box Container
            const container = document.createElement('div');
            container.id = 'motaaked-checkout-container';
            container.style.cssText = [
                'position: relative',
                'width: 100%',
                'max-width: 480px',
                'height: 92vh',
                'max-height: 720px',
                'background: transparent',
                'border-radius: 20px',
                'box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.65)',
                'overflow: hidden',
                'transform: scale(0.96) translateY(12px)',
                'transition: transform 0.25s cubic-bezier(0.16, 1, 0.3, 1)',
                'display: flex',
                'flex-direction: column',
            ].join(';');

            // 3. Close Button
            const closeBtn = document.createElement('button');
            closeBtn.id = 'motaaked-checkout-close-btn';
            closeBtn.innerHTML = '&times;';
            closeBtn.setAttribute('aria-label', 'Close Checkout');
            closeBtn.style.cssText = [
                'position: absolute',
                'top: 10px',
                'left: 12px',
                'width: 32px',
                'height: 32px',
                'border-radius: 50%',
                'background: rgba(0, 0, 0, 0.45)',
                'border: 1px solid rgba(255, 255, 255, 0.2)',
                'color: #ffffff',
                'font-size: 20px',
                'font-weight: 300',
                'line-height: 1',
                'cursor: pointer',
                'display: flex',
                'align-items: center',
                'justify-content: center',
                'z-index: 10',
                'transition: background-color 0.15s, transform 0.15s',
            ].join(';');

            closeBtn.onmouseenter = function () {
                closeBtn.style.backgroundColor = 'rgba(239, 68, 68, 0.85)';
                closeBtn.style.transform = 'scale(1.08)';
            };
            closeBtn.onmouseleave = function () {
                closeBtn.style.backgroundColor = 'rgba(0, 0, 0, 0.45)';
                closeBtn.style.transform = 'scale(1)';
            };

            const self = this;
            closeBtn.onclick = function (e) {
                e.stopPropagation();
                if (typeof options.onCancel === 'function') {
                    options.onCancel();
                }
                self.close();
            };

            // 4. Loading Spinner Indicator
            const spinner = document.createElement('div');
            spinner.id = 'motaaked-checkout-spinner';
            spinner.style.cssText = [
                'position: absolute',
                'top: 50%',
                'left: 50%',
                'transform: translate(-50%, -50%)',
                'width: 44px',
                'height: 44px',
                'border: 4px solid rgba(16, 185, 129, 0.2)',
                'border-top-color: #10b981',
                'border-radius: 50%',
                'animation: motaaked-spin 0.8s linear infinite',
                'z-index: 1',
            ].join(';');

            // Inject CSS keyframes if not present
            if (!document.getElementById('motaaked-checkout-styles')) {
                const styleSheet = document.createElement('style');
                styleSheet.id = 'motaaked-checkout-styles';
                styleSheet.textContent = '@keyframes motaaked-spin { 0% { transform: translate(-50%, -50%) rotate(0deg); } 100% { transform: translate(-50%, -50%) rotate(360deg); } }';
                document.head.appendChild(styleSheet);
            }

            // 5. Iframe Element
            const iframe = document.createElement('iframe');
            iframe.src = targetUrl;
            iframe.style.cssText = [
                'width: 100%',
                'height: 100%',
                'border: none',
                'background: transparent',
                'position: relative',
                'z-index: 2',
                'opacity: 0',
                'transition: opacity 0.3s ease-in',
            ].join(';');

            iframe.onload = function () {
                iframe.style.opacity = '1';
                if (spinner && spinner.parentNode) {
                    spinner.parentNode.removeChild(spinner);
                }
            };

            // Assemble DOM
            container.appendChild(closeBtn);
            container.appendChild(spinner);
            container.appendChild(iframe);
            backdrop.appendChild(container);
            document.body.appendChild(backdrop);

            // Backdrop click closes (optional)
            backdrop.onclick = function (e) {
                if (e.target === backdrop) {
                    if (typeof options.onCancel === 'function') {
                        options.onCancel();
                    }
                    self.close();
                }
            };

            // Keyboard Escape listener
            keydownListener = function (e) {
                if (e.key === 'Escape' || e.keyCode === 27) {
                    if (typeof options.onCancel === 'function') {
                        options.onCancel();
                    }
                    self.close();
                }
            };
            window.addEventListener('keydown', keydownListener);

            // PostMessage Listener
            messageListener = function (event) {
                if (!event.data || typeof event.data !== 'object') return;

                // Security: Verify message originated from this modal's iframe contentWindow
                if (iframe && iframe.contentWindow && event.source !== iframe.contentWindow) {
                    return;
                }

                // Security: Validate event.origin against configured gateway baseUrl
                if (self.baseUrl && event.origin) {
                    try {
                        const expectedOrigin = new URL(self.baseUrl, window.location.href).origin;
                        if (event.origin !== expectedOrigin && event.origin !== window.location.origin) {
                            console.warn('[MotaakedCheckout] Rejected postMessage from untrusted origin:', event.origin);
                            return;
                        }
                    } catch (e) {}
                }

                const msg = event.data;

                if (msg.event === 'motaaked:payment_success') {
                    if (typeof options.onSuccess === 'function') {
                        options.onSuccess(msg);
                    }
                } else if (msg.event === 'motaaked:checkout_cancelled') {
                    if (typeof options.onCancel === 'function') {
                        options.onCancel();
                    }
                    self.close();
                } else if (msg.event === 'motaaked:close_modal') {
                    self.close();
                }
            };
            window.addEventListener('message', messageListener);

            // Trigger enter animation
            requestAnimationFrame(() => {
                backdrop.style.opacity = '1';
                container.style.transform = 'scale(1) translateY(0)';
            });

            activeModal = {
                backdrop: backdrop,
                container: container,
                options: options,
            };
        },

        /**
         * Closes and removes the active modal.
         */
        close: function () {
            if (!activeModal) return;

            const modal = activeModal;
            activeModal = null;

            // Remove event listeners
            if (messageListener) {
                window.removeEventListener('message', messageListener);
                messageListener = null;
            }
            if (keydownListener) {
                window.removeEventListener('keydown', keydownListener);
                keydownListener = null;
            }

            // Animate exit
            modal.backdrop.style.opacity = '0';
            modal.container.style.transform = 'scale(0.96) translateY(12px)';

            setTimeout(() => {
                if (modal.backdrop.parentNode) {
                    modal.backdrop.parentNode.removeChild(modal.backdrop);
                }
                if (typeof modal.options.onClose === 'function') {
                    modal.options.onClose();
                }
            }, 260);
        },
    };

    // Global namespace export
    global.MotaakedCheckout = MotaakedCheckout;
    global.InstaTakeedCheckout = MotaakedCheckout; // Alias for backwards-compatibility

})(typeof window !== 'undefined' ? window : this);
