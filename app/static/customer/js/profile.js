(function() {
  'use strict';

  // ========== STATE ==========
  const state = {
    currentTab: 'profile',
    editingAddressId: null,
    deletingAddressId: null
  };

  // ========== INITIALIZE ==========
  function init() {
    initTabs();
    initAddressModal();
    initPasswordValidation();
    initDeleteModal();
    handleAnchorTabs();
    
    console.log('Profile page initialized');
  }

  // ========== TAB NAVIGATION ==========
  function initTabs() {
    const navButtons = document.querySelectorAll('.nav-item[data-tab]');
    const tabPanels = document.querySelectorAll('.tab-panel');

    navButtons.forEach(button => {
      button.addEventListener('click', () => {
        const tabName = button.dataset.tab;
        
        // Update active states
        navButtons.forEach(btn => btn.classList.remove('active'));
        tabPanels.forEach(panel => panel.classList.remove('active'));
        
        button.classList.add('active');
        const targetPanel = document.getElementById(`tab-${tabName}`);
        if (targetPanel) {
          targetPanel.classList.add('active');
        }

        // Update URL hash
        window.history.replaceState(null, '', `#tab-${tabName}`);
        
        state.currentTab = tabName;

        // Smooth scroll to top of content
        const contentArea = document.querySelector('.profile-content');
        if (contentArea && window.innerWidth <= 1024) {
          contentArea.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      });
    });
  }

  function handleAnchorTabs() {
    const hash = window.location.hash;
    if (hash && hash.startsWith('#tab-')) {
      const tabName = hash.replace('#tab-', '');
      const button = document.querySelector(`[data-tab="${tabName}"]`);
      if (button) {
        setTimeout(() => {
          button.click();
        }, 100);
      }
    }
  }

  // ========== ADDRESS MODAL ==========
  function initAddressModal() {
    const addAddressBtn = document.getElementById('addAddressBtn');
    const addFirstAddressBtn = document.getElementById('addFirstAddressBtn');
    
    if (addAddressBtn) {
      addAddressBtn.addEventListener('click', () => openAddressModal());
    }
    
    if (addFirstAddressBtn) {
      addFirstAddressBtn.addEventListener('click', () => openAddressModal());
    }

    // Close on escape key
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        closeAddressModal();
        closeDeleteModal();
      }
    });
  }

  function openAddressModal(addressId = null) {
    const modal = document.getElementById('addressModal');
    const form = document.getElementById('addressForm');
    const title = document.getElementById('addressModalTitle');
    
    if (!modal || !form) return;

    state.editingAddressId = addressId;

    if (addressId) {
      // Edit mode
      title.textContent = 'Edit Address';
      form.action = `/address/${addressId}/edit`;
      
      // Fetch address data from the card
      const card = document.querySelector(`[data-address-id="${addressId}"]`);
      if (card) {
        populateAddressForm(card);
      }
    } else {
      // Add mode
      title.textContent = 'Add New Address';
      form.action = '/address/add';
      form.reset();
    }

    modal.classList.add('active');
    document.body.style.overflow = 'hidden';

    // Focus first input
    setTimeout(() => {
      const firstInput = form.querySelector('input:not([readonly])');
      if (firstInput) firstInput.focus();
    }, 100);
  }

  function closeAddressModal() {
    const modal = document.getElementById('addressModal');
    const form = document.getElementById('addressForm');
    
    if (!modal) return;

    modal.classList.remove('active');
    document.body.style.overflow = '';
    
    if (form) {
      form.reset();
    }
    
    state.editingAddressId = null;
  }

  function populateAddressForm(card) {
    // This would normally fetch data from the server or parse from the card
    // For now, we'll use data attributes or parse the displayed text
    const addressData = {
      name: card.dataset.name || '',
      phone: card.dataset.phone || '',
      line1: card.dataset.line1 || '',
      line2: card.dataset.line2 || '',
      city: card.dataset.city || '',
      state: card.dataset.state || '',
      postal_code: card.dataset.postal || '',
      country: card.dataset.country || 'India',
      is_default: card.classList.contains('address-default')
    };

    // Populate form fields
    document.getElementById('addr_name').value = addressData.name;
    document.getElementById('addr_phone').value = addressData.phone;
    document.getElementById('addr_line1').value = addressData.line1;
    document.getElementById('addr_line2').value = addressData.line2;
    document.getElementById('addr_city').value = addressData.city;
    document.getElementById('addr_state').value = addressData.state;
    document.getElementById('addr_postal').value = addressData.postal_code;
    document.getElementById('addr_country').value = addressData.country;
    document.getElementById('addr_default').checked = addressData.is_default;
  }

  // ========== EDIT ADDRESS ==========
  window.editAddress = function(addressId) {
    // Fetch address data and populate modal
    const addressCard = findAddressCard(addressId);
    if (!addressCard) {
      showNotification('Address not found', 'error');
      return;
    }

    const modal = document.getElementById('addressModal');
    const form = document.getElementById('addressForm');
    const title = document.getElementById('addressModalTitle');
    
    if (!modal || !form) return;

    // Set form to edit mode
    title.textContent = 'Edit Address';
    form.action = `/address/${addressId}/edit`;
    state.editingAddressId = addressId;

    // Parse address data from card
    const addressData = parseAddressFromCard(addressCard);
    
    // Populate form
    document.getElementById('addr_name').value = addressData.name || '';
    document.getElementById('addr_phone').value = addressData.phone || '';
    document.getElementById('addr_line1').value = addressData.line1 || '';
    document.getElementById('addr_line2').value = addressData.line2 || '';
    document.getElementById('addr_city').value = addressData.city || '';
    document.getElementById('addr_state').value = addressData.state || '';
    document.getElementById('addr_postal').value = addressData.postal || '';
    document.getElementById('addr_country').value = addressData.country || 'India';
    document.getElementById('addr_default').checked = addressData.is_default || false;

    // Open modal
    modal.classList.add('active');
    document.body.style.overflow = 'hidden';

    // Focus first input
    setTimeout(() => {
      document.getElementById('addr_name').focus();
    }, 100);
  };

  function findAddressCard(addressId) {
    const cards = document.querySelectorAll('.address-card');
    for (let card of cards) {
      const editBtn = card.querySelector(`[onclick*="${addressId}"]`);
      if (editBtn) return card;
    }
    return null;
  }

  function parseAddressFromCard(card) {
    const name = card.querySelector('.address-name')?.textContent.trim() || '';
    const phoneEl = card.querySelector('.address-phone');
    const phone = phoneEl ? phoneEl.textContent.replace('📱', '').trim() : '';
    
    const addressText = card.querySelector('.address-text')?.innerHTML || '';
    const lines = addressText.split('<br>').map(l => l.trim()).filter(l => l);
    
    // Parse address lines
    const line1 = lines[0] || '';
    let line2 = '';
    let city = '';
    let state = '';
    let postal = '';
    let country = 'India';

    if (lines.length >= 2) {
      // Check if second line is city/state or another address line
      const secondLine = lines[1];
      if (secondLine.includes(',')) {
        // It's likely city, state postal
        const parts = secondLine.split(',').map(p => p.trim());
        city = parts[0] || '';
        if (parts[1]) {
          const statePostal = parts[1].split(/\s+/);
          state = statePostal.slice(0, -1).join(' ') || '';
          postal = statePostal[statePostal.length - 1] || '';
        }
      } else {
        line2 = secondLine;
        if (lines[2]) {
          const parts = lines[2].split(',').map(p => p.trim());
          city = parts[0] || '';
          if (parts[1]) {
            const statePostal = parts[1].split(/\s+/);
            state = statePostal.slice(0, -1).join(' ') || '';
            postal = statePostal[statePostal.length - 1] || '';
          }
        }
      }
    }

    if (lines.length >= 3 && !line2) {
      country = lines[lines.length - 1] || 'India';
    } else if (lines.length >= 4) {
      country = lines[lines.length - 1] || 'India';
    }

    const is_default = card.classList.contains('address-default');

    return { name, phone, line1, line2, city, state, postal, country, is_default };
  }

  // ========== DELETE ADDRESS ==========
  window.deleteAddress = function(addressId) {
    state.deletingAddressId = addressId;
    openDeleteModal(addressId);
  };

  function initDeleteModal() {
    // Modal is controlled by window functions
  }

  function openDeleteModal(addressId) {
    const modal = document.getElementById('deleteModal');
    const form = document.getElementById('deleteForm');
    
    if (!modal || !form) return;

    form.action = `/address/${addressId}/delete`;
    modal.classList.add('active');
    document.body.style.overflow = 'hidden';
  }

  window.closeDeleteModal = function() {
    const modal = document.getElementById('deleteModal');
    if (!modal) return;

    modal.classList.remove('active');
    document.body.style.overflow = '';
    state.deletingAddressId = null;
  };

  window.closeAddressModal = closeAddressModal;

  // ========== PASSWORD VALIDATION ==========
  function initPasswordValidation() {
    const form = document.getElementById('passwordForm');
    if (!form) return;

    const newPassword = document.getElementById('new_password');
    const confirmPassword = document.getElementById('new_password_confirm');

    if (!newPassword || !confirmPassword) return;

    // Real-time validation
    confirmPassword.addEventListener('input', () => {
      if (confirmPassword.value && newPassword.value !== confirmPassword.value) {
        confirmPassword.setCustomValidity('Passwords do not match');
      } else {
        confirmPassword.setCustomValidity('');
      }
    });

    newPassword.addEventListener('input', () => {
      if (confirmPassword.value && newPassword.value !== confirmPassword.value) {
        confirmPassword.setCustomValidity('Passwords do not match');
      } else {
        confirmPassword.setCustomValidity('');
      }
    });

    // Form submission validation
    form.addEventListener('submit', (e) => {
      const current = document.getElementById('current_password').value;
      const newPw = newPassword.value;
      const confirmPw = confirmPassword.value;

      if (!current || !newPw || !confirmPw) {
        e.preventDefault();
        showNotification('Please fill all password fields', 'warning');
        return;
      }

      if (newPw !== confirmPw) {
        e.preventDefault();
        showNotification('New passwords do not match', 'error');
        confirmPassword.focus();
        return;
      }

      if (newPw.length < 8) {
        e.preventDefault();
        showNotification('Password must be at least 8 characters', 'warning');
        newPassword.focus();
        return;
      }

      // Show loading state
      const submitBtn = form.querySelector('button[type="submit"]');
      if (submitBtn) {
        submitBtn.disabled = true;
        const originalText = submitBtn.innerHTML;
        submitBtn.innerHTML = '<svg class="spinner" width="16" height="16" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none" opacity="0.25"/><path d="M4 12a8 8 0 018-8" stroke="currentColor" stroke-width="4" fill="none" stroke-linecap="round"/></svg> Updating...';
        
        setTimeout(() => {
          submitBtn.disabled = false;
          submitBtn.innerHTML = originalText;
        }, 3000);
      }
    });
  }

  // ========== PASSWORD TOGGLE ==========
  window.togglePassword = function(inputId) {
    const input = document.getElementById(inputId);
    const button = input?.parentElement.querySelector('.password-toggle');
    
    if (!input || !button) return;

    if (input.type === 'password') {
      input.type = 'text';
      button.innerHTML = `
        <svg class="eye-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path>
          <line x1="1" y1="1" x2="23" y2="23"></line>
        </svg>
      `;
    } else {
      input.type = 'password';
      button.innerHTML = `
        <svg class="eye-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
          <circle cx="12" cy="12" r="3"></circle>
        </svg>
      `;
    }
  };

  // ========== NOTIFICATIONS ==========
  function showNotification(message, type = 'info') {
    const container = document.querySelector('.flash-messages') || createFlashContainer();
    
    const flash = document.createElement('div');
    flash.className = `flash-message flash-${type}`;
    
    let icon = '';
    if (type === 'success') {
      icon = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg>';
    } else if (type === 'error' || type === 'danger') {
      icon = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>';
    } else if (type === 'warning') {
      icon = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>';
    } else {
      icon = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>';
    }
    
    flash.innerHTML = `
      <div class="flash-icon">${icon}</div>
      <span>${message}</span>
      <button class="flash-close" onclick="this.parentElement.remove()">×</button>
    `;
    
    container.appendChild(flash);
    
    // Auto remove after 5 seconds
    setTimeout(() => {
      if (flash.parentElement) {
        flash.style.animation = 'slideOutUp 0.3s ease';
        setTimeout(() => flash.remove(), 300);
      }
    }, 5000);
  }

  function createFlashContainer() {
    const container = document.createElement('div');
    container.className = 'flash-messages';
    
    const profileContent = document.querySelector('.profile-content');
    if (profileContent) {
      profileContent.parentElement.insertBefore(container, profileContent);
    } else {
      document.querySelector('.profile-container').prepend(container);
    }
    
    return container;
  }

  // ========== FORM ENHANCEMENTS ==========
  function enhanceForms() {
    // Add loading states to all forms
    document.querySelectorAll('form').forEach(form => {
      form.addEventListener('submit', function(e) {
        const submitBtn = this.querySelector('button[type="submit"]');
        if (submitBtn && !submitBtn.disabled) {
          submitBtn.disabled = true;
          const originalText = submitBtn.innerHTML;
          
          // Add spinner
          submitBtn.innerHTML = `
            <svg class="spinner" width="16" height="16" viewBox="0 0 24 24" style="animation: spin 0.8s linear infinite;">
              <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none" opacity="0.25"/>
              <path d="M4 12a8 8 0 018-8" stroke="currentColor" stroke-width="4" fill="none" stroke-linecap="round"/>
            </svg>
            Processing...
          `;
          
          // Restore after 3 seconds (in case of client-side validation failure)
          setTimeout(() => {
            if (submitBtn.disabled) {
              submitBtn.disabled = false;
              submitBtn.innerHTML = originalText;
            }
          }, 3000);
        }
      });
    });

    // Phone number formatting
    const phoneInputs = document.querySelectorAll('input[type="tel"]');
    phoneInputs.forEach(input => {
      input.addEventListener('input', function(e) {
        // Remove non-numeric characters except + and spaces
        this.value = this.value.replace(/[^0-9+\s-]/g, '');
      });
    });

    // Postal code validation
    const postalInputs = document.querySelectorAll('input[name="postal_code"]');
    postalInputs.forEach(input => {
      input.addEventListener('input', function(e) {
        this.value = this.value.replace(/[^0-9]/g, '').slice(0, 6);
      });
    });
  }

  // ========== UTILITY FUNCTIONS ==========
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

  // ========== AUTO-SAVE DRAFT (Optional Enhancement) ==========
  function initAutoSave() {
    const forms = document.querySelectorAll('form[data-autosave]');
    
    forms.forEach(form => {
      const inputs = form.querySelectorAll('input, textarea, select');
      const formId = form.id || form.action;
      
      inputs.forEach(input => {
        input.addEventListener('input', debounce(() => {
          const formData = new FormData(form);
          const data = Object.fromEntries(formData.entries());
          localStorage.setItem(`draft_${formId}`, JSON.stringify(data));
        }, 1000));
      });

      // Restore draft on load
      const draft = localStorage.getItem(`draft_${formId}`);
      if (draft) {
        try {
          const data = JSON.parse(draft);
          Object.entries(data).forEach(([name, value]) => {
            const input = form.querySelector(`[name="${name}"]`);
            if (input && !input.value) {
              input.value = value;
            }
          });
        } catch (e) {
          console.error('Error restoring draft:', e);
        }
      }
    });
  }

  // ========== SMOOTH SCROLL ENHANCEMENTS ==========
  function initSmoothScroll() {
    // Smooth scroll for anchor links
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
      anchor.addEventListener('click', function (e) {
        const href = this.getAttribute('href');
        if (href !== '#' && href.length > 1) {
          e.preventDefault();
          const target = document.querySelector(href);
          if (target) {
            target.scrollIntoView({ behavior: 'smooth', block: 'start' });
          }
        }
      });
    });
  }

  // ========== KEYBOARD SHORTCUTS ==========
  function initKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
      // Ctrl/Cmd + K to focus search (if exists)
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        const searchInput = document.querySelector('input[type="search"]');
        if (searchInput) searchInput.focus();
      }

      // Esc to close modals
      if (e.key === 'Escape') {
        closeAddressModal();
        closeDeleteModal();
      }
    });
  }

  // ========== ADD CSS ANIMATIONS ==========
  function addDynamicStyles() {
    const style = document.createElement('style');
    style.textContent = `
      @keyframes spin {
        to { transform: rotate(360deg); }
      }
      
      @keyframes slideOutUp {
        from {
          opacity: 1;
          transform: translateY(0);
        }
        to {
          opacity: 0;
          transform: translateY(-20px);
        }
      }
      
      .spinner {
        animation: spin 0.8s linear infinite;
      }
    `;
    document.head.appendChild(style);
  }

  // ========== INITIALIZE ON DOM READY ==========
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      init();
      enhanceForms();
      initSmoothScroll();
      initKeyboardShortcuts();
      addDynamicStyles();
    });
  } else {
    init();
    enhanceForms();
    initSmoothScroll();
    initKeyboardShortcuts();
    addDynamicStyles();
  }

  // ========== EXPOSE PUBLIC API ==========
  window.ProfileApp = {
    openAddressModal,
    closeAddressModal,
    closeDeleteModal,
    editAddress: window.editAddress,
    deleteAddress: window.deleteAddress,
    togglePassword: window.togglePassword,
    showNotification
  };

})();