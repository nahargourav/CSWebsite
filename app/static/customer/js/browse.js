(function() {
  'use strict';

  // ========== STATE MANAGEMENT ==========
  const state = {
    filters: {
      category: [],
      brand: [],
      color: [],
      size: [],
      tag: [],
      min_price: null,
      max_price: null,
      min_rating: null
    },
    search: '',
    sort: 'relevance',
    page: 1,
    per_page: 24,
    total: 0,
    variants: [],
    filterOptions: {},
    view: 'grid',
    priceRange: { min: 0, max: 100 }
  };

  // ========== DOM ELEMENTS ==========
  const elements = {
    searchInput: document.getElementById('searchInput'),
    sortSelect: document.getElementById('sortSelect'),
    filterToggleBtn: document.getElementById('filterToggleBtn'),
    filtersSidebar: document.getElementById('filtersSidebar'),
    filterOverlay: document.getElementById('filterOverlay'),
    clearAllFilters: document.getElementById('clearAllFilters'),
    mobileCloseFilters: document.getElementById('mobileCloseFilters'),
    activeFilters: document.getElementById('activeFilters'),
    productsGrid: document.getElementById('productsGrid'),
    loadingContainer: document.getElementById('loadingContainer'),
    emptyState: document.getElementById('emptyState'),
    resultsCount: document.getElementById('resultsCount'),
    pagination: document.getElementById('pagination'),
    minPriceSlider: document.getElementById('minPriceSlider'),
    maxPriceSlider: document.getElementById('maxPriceSlider'),
    minPriceDisplay: document.getElementById('minPriceDisplay'),
    maxPriceDisplay: document.getElementById('maxPriceDisplay'),
    priceSliderTrack: document.getElementById('priceSliderTrack'),
    categoryFilters: document.getElementById('categoryFilters'),
    brandFilters: document.getElementById('brandFilters'),
    colorFilters: document.getElementById('colorFilters'),
    sizeFilters: document.getElementById('sizeFilters'),
    tagFilters: document.getElementById('tagFilters'),
    ratingFilters: document.getElementById('ratingFilters'),
    scrollToTop: document.getElementById('scrollToTop')
  };

  // ========== API CALLS ==========
  async function fetchFilters() {
    try {
      const response = await fetch('/filters');
      if (!response.ok) throw new Error('Failed to fetch filters');
      state.filterOptions = await response.json();
      renderFilterOptions();
      initializePriceSlider();
    } catch (error) {
      console.error('Error fetching filters:', error);
    }
  }

  async function fetchVariants() {
    showLoading();
    
    try {
      const params = new URLSearchParams();
      
      // Add search
      if (state.search) params.append('q', state.search);
      
      // Add filters
      state.filters.category.forEach(cat => params.append('category', cat));
      state.filters.brand.forEach(brand => params.append('brand', brand));
      state.filters.color.forEach(color => params.append('color', color));
      state.filters.size.forEach(size => params.append('size', size));
      state.filters.tag.forEach(tag => params.append('tag', tag));
      
      if (state.filters.min_price !== null) params.append('min_price', state.filters.min_price);
      if (state.filters.max_price !== null) params.append('max_price', state.filters.max_price);
      if (state.filters.min_rating !== null) params.append('min_rating', state.filters.min_rating);
      
      // Add sort and pagination
      params.append('sort', state.sort);
      params.append('page', state.page);
      params.append('per_page', state.per_page);
      
      const response = await fetch(`/variants?${params.toString()}`);
      if (!response.ok) throw new Error('Failed to fetch variants');
      
      const data = await response.json();
      state.variants = data.variants;
      state.total = data.total;
      
      hideLoading();
      renderProducts();
      renderPagination();
      updateResultsCount();
      updateActiveFilters();
      await checkWishlistStatuses();
      announceResults();
      updateURLParams();
      
    } catch (error) {
      console.error('Error fetching variants:', error);
      hideLoading();
      showEmptyState();
    }
  }

  // ========== PRICE SLIDER FUNCTIONS ==========
  function initializePriceSlider() {
    if (!state.filterOptions.min_price || !state.filterOptions.max_price) return;
    
    state.priceRange = {
      min: state.filterOptions.min_price,
      max: state.filterOptions.max_price
    };
    
    updatePriceDisplay();
    updatePriceTrack();
    
    // Event listeners for sliders
    let priceTimeout;
    
    elements.minPriceSlider.addEventListener('input', function() {
      let minVal = parseInt(this.value);
      let maxVal = parseInt(elements.maxPriceSlider.value);
      
      if (minVal >= maxVal) {
        this.value = maxVal - 1;
        minVal = maxVal - 1;
      }
      
      updatePriceDisplay();
      updatePriceTrack();
    });
    
    elements.maxPriceSlider.addEventListener('input', function() {
      let maxVal = parseInt(this.value);
      let minVal = parseInt(elements.minPriceSlider.value);
      
      if (maxVal <= minVal) {
        this.value = minVal + 1;
        maxVal = minVal + 1;
      }
      
      updatePriceDisplay();
      updatePriceTrack();
    });
    
    elements.minPriceSlider.addEventListener('change', function() {
      clearTimeout(priceTimeout);
      priceTimeout = setTimeout(() => {
        applyPriceFilter();
      }, 500);
    });
    
    elements.maxPriceSlider.addEventListener('change', function() {
      clearTimeout(priceTimeout);
      priceTimeout = setTimeout(() => {
        applyPriceFilter();
      }, 500);
    });
  }
  
  function updatePriceDisplay() {
    const minPercent = parseInt(elements.minPriceSlider.value);
    const maxPercent = parseInt(elements.maxPriceSlider.value);
    
    const minPrice = Math.round(state.priceRange.min + (state.priceRange.max - state.priceRange.min) * (minPercent / 100));
    const maxPrice = Math.round(state.priceRange.min + (state.priceRange.max - state.priceRange.min) * (maxPercent / 100));
    
    elements.minPriceDisplay.textContent = `₹${minPrice}`;
    elements.maxPriceDisplay.textContent = `₹${maxPrice}`;
  }
  
  function updatePriceTrack() {
    const minPercent = parseInt(elements.minPriceSlider.value);
    const maxPercent = parseInt(elements.maxPriceSlider.value);
    
    elements.priceSliderTrack.style.left = `${minPercent}%`;
    elements.priceSliderTrack.style.width = `${maxPercent - minPercent}%`;
  }
  
  function applyPriceFilter() {
    const minPercent = parseInt(elements.minPriceSlider.value);
    const maxPercent = parseInt(elements.maxPriceSlider.value);
    
    state.filters.min_price = Math.round(state.priceRange.min + (state.priceRange.max - state.priceRange.min) * (minPercent / 100));
    state.filters.max_price = Math.round(state.priceRange.min + (state.priceRange.max - state.priceRange.min) * (maxPercent / 100));
    
    state.page = 1;
    fetchVariants();
  }

  // ========== RENDER FUNCTIONS ==========
  function renderFilterOptions() {
    // Categories
    elements.categoryFilters.innerHTML = state.filterOptions.categories.map(cat => `
      <label class="filter-option" data-type="category" data-value="${cat}">
        <div class="filter-checkbox"></div>
        <span class="filter-label">${cat}</span>
      </label>
    `).join('');

    // Brands
    elements.brandFilters.innerHTML = state.filterOptions.brands.map(brand => `
      <label class="filter-option" data-type="brand" data-value="${brand}">
        <div class="filter-checkbox"></div>
        <span class="filter-label">${brand}</span>
      </label>
    `).join('');

    // Colors
    elements.colorFilters.innerHTML = state.filterOptions.colors.map(color => `
      <div class="color-option" data-type="color" data-value="${color}">
        <div class="color-swatch" style="background-color: ${color}"></div>
        <span class="filter-label">${color}</span>
      </div>
    `).join('');

    // Sizes
    elements.sizeFilters.innerHTML = state.filterOptions.sizes.map(size => `
      <label class="filter-option" data-type="size" data-value="${size}">
        <div class="filter-checkbox"></div>
        <span class="filter-label">${size}</span>
      </label>
    `).join('');

    // Tags
    elements.tagFilters.innerHTML = state.filterOptions.tags.map(tag => `
      <label class="filter-option" data-type="tag" data-value="${tag}">
        <div class="filter-checkbox"></div>
        <span class="filter-label">${tag}</span>
      </label>
    `).join('');

    // Ratings
    elements.ratingFilters.innerHTML = state.filterOptions.rating_options.map(rating => `
      <label class="rating-option" data-type="rating" data-value="${rating}">
        <div class="filter-checkbox"></div>
        <div class="rating-stars">${'★'.repeat(rating)}${'☆'.repeat(5 - rating)}</div>
        <span class="rating-label">& Up</span>
      </label>
    `).join('');

    attachFilterListeners();
  }

  function renderProducts() {
    if (state.variants.length === 0) {
      showEmptyState();
      return;
    }

    hideEmptyState();

    const isMobile = window.innerWidth <= 768;

    elements.productsGrid.innerHTML = state.variants.map(variant => {
      const ratingStars = '★'.repeat(Math.floor(variant.rating_avg)) + 
                         '☆'.repeat(5 - Math.floor(variant.rating_avg));
      
      return `
        <div class="product-card" data-variant-id="${variant.variant_id}" data-product-id="${variant.product_id}" data-variant-sku="${variant.variant_sku || ''}">
          <div class="product-image-wrapper">
            <img 
              src="${variant.image || '/static/images/placeholder-420x280.png'}" 
              alt="${variant.product_name}"
              class="product-image"
              loading="lazy"
            >
            ${variant.brand ? `<div class="product-badge">${variant.brand}</div>` : ''}
            <button class="wishlist-btn" data-variant-id="${variant.variant_id}" data-product-id="${variant.product_id}">
              ♡
            </button>
            ${variant.color ? `
              <div class="product-colors">
                <div class="color-dot" style="background-color: ${variant.color_hex || variant.color}" title="${variant.color}"></div>
              </div>
            ` : ''}
          </div>
          <div class="product-body">
            <h3 class="product-name">${variant.product_name}</h3>
            <div class="product-meta">
              <div class="product-rating">
                <span class="rating-stars-display">${ratingStars}</span>
                <span class="rating-value">${variant.rating_avg.toFixed(1)}</span>
              </div>
              ${variant.reviews_count > 0 ? `<span class="reviews-count">(${variant.reviews_count})</span>` : ''}
            </div>
            <div class="product-pricing">
              <div class="product-price">₹${variant.price}</div>
            </div>
            ${!isMobile ? `
              <div class="product-footer">
                <button class="btn-view-details" onclick="event.stopPropagation(); BrowseApp.viewProduct('${variant.product_id}', '${variant.variant_id}', '${variant.variant_sku}')">
                  View Details
                </button>
              </div>
            ` : ''}
          </div>
        </div>
      `;
    }).join('');

    attachProductListeners();
  }

  function renderPagination() {
    const totalPages = Math.ceil(state.total / state.per_page);
    
    if (totalPages <= 1) {
      elements.pagination.innerHTML = '';
      return;
    }

    let paginationHTML = `
      <button class="pagination-btn" ${state.page === 1 ? 'disabled' : ''} onclick="BrowseApp.changePage(${state.page - 1})">
        ‹ Prev
      </button>
    `;

    // Page numbers
    const maxVisible = 5;
    let startPage = Math.max(1, state.page - Math.floor(maxVisible / 2));
    let endPage = Math.min(totalPages, startPage + maxVisible - 1);
    
    if (endPage - startPage < maxVisible - 1) {
      startPage = Math.max(1, endPage - maxVisible + 1);
    }

    if (startPage > 1) {
      paginationHTML += `<button class="pagination-btn" onclick="BrowseApp.changePage(1)">1</button>`;
      if (startPage > 2) {
        paginationHTML += `<span class="pagination-info">...</span>`;
      }
    }

    for (let i = startPage; i <= endPage; i++) {
      paginationHTML += `
        <button class="pagination-btn ${i === state.page ? 'active' : ''}" onclick="BrowseApp.changePage(${i})">
          ${i}
        </button>
      `;
    }

    if (endPage < totalPages) {
      if (endPage < totalPages - 1) {
        paginationHTML += `<span class="pagination-info">...</span>`;
      }
      paginationHTML += `<button class="pagination-btn" onclick="BrowseApp.changePage(${totalPages})">${totalPages}</button>`;
    }

    paginationHTML += `
      <button class="pagination-btn" ${state.page === totalPages ? 'disabled' : ''} onclick="BrowseApp.changePage(${state.page + 1})">
        Next ›
      </button>
    `;

    elements.pagination.innerHTML = paginationHTML;
  }

  function updateResultsCount() {
    elements.resultsCount.textContent = state.total;
  }

  function updateActiveFilters() {
    const tags = [];
    
    // Collect all active filters
    ['category', 'brand', 'color', 'size', 'tag'].forEach(type => {
      state.filters[type].forEach(value => {
        tags.push({ type, value, label: value });
      });
    });

    if (state.filters.min_price || state.filters.max_price) {
      const priceLabel = `₹${state.filters.min_price || state.priceRange.min} - ₹${state.filters.max_price || state.priceRange.max}`;
      tags.push({ type: 'price', value: 'price', label: priceLabel });
    }

    if (state.filters.min_rating) {
      tags.push({ type: 'rating', value: state.filters.min_rating, label: `${state.filters.min_rating}★ & Up` });
    }

    elements.activeFilters.innerHTML = tags.map(tag => `
      <div class="filter-tag">
        <span>${tag.label}</span>
        <span class="filter-tag-remove" onclick="BrowseApp.removeFilter('${tag.type}', '${tag.value}')">×</span>
      </div>
    `).join('');
  }

  // ========== EVENT HANDLERS ==========
  function attachFilterListeners() {
    // Standard checkbox filters
    document.querySelectorAll('.filter-option').forEach(option => {
      option.addEventListener('click', function(e) {
        e.stopPropagation();
        const type = this.dataset.type;
        const value = this.dataset.value;
        toggleFilter(type, value);
        this.querySelector('.filter-checkbox').classList.toggle('checked');
      });
    });

    // Color filters
    document.querySelectorAll('.color-option').forEach(option => {
      option.addEventListener('click', function(e) {
        e.stopPropagation();
        const type = this.dataset.type;
        const value = this.dataset.value;
        toggleFilter(type, value);
        this.querySelector('.color-swatch').classList.toggle('selected');
      });
    });

    // Rating filters
    document.querySelectorAll('.rating-option').forEach(option => {
      option.addEventListener('click', function(e) {
        e.stopPropagation();
        const value = parseFloat(this.dataset.value);
        
        // Clear other ratings
        document.querySelectorAll('.rating-option .filter-checkbox').forEach(cb => {
          cb.classList.remove('checked');
        });
        
        state.filters.min_rating = value;
        this.querySelector('.filter-checkbox').classList.add('checked');
        state.page = 1;
        fetchVariants();
      });
    });

    // Filter group toggle
    document.querySelectorAll('.filter-group-title').forEach(title => {
      title.addEventListener('click', function(e) {
        e.stopPropagation();
        this.classList.toggle('collapsed');
        const options = this.parentElement.querySelector('.filter-options');
        if (options) {
          options.classList.toggle('collapsed');
        }
      });
    });
  }

  function attachProductListeners() {
    // Wishlist buttons
    document.querySelectorAll('.wishlist-btn').forEach(btn => {
      btn.addEventListener('click', async function(e) {
        e.stopPropagation();
        const variantId = this.dataset.variantId;
        const productId = this.dataset.productId;
        
        try {
          const response = await fetch('/wishlist/toggle', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-Requested-With': 'XMLHttpRequest'
            },
            body: JSON.stringify({ variant_id: variantId, product_id: productId })
          });

          if (response.status === 401) {
            window.location.href = '/login';
            return;
          }

          const data = await response.json();
          if (data.ok) {
            this.classList.toggle('active');
            this.textContent = this.classList.contains('active') ? '♥' : '♡';
          }
        } catch (error) {
          console.error('Error toggling wishlist:', error);
        }
      });
    });

    // Product card click
    document.querySelectorAll('.product-card').forEach(card => {
      card.addEventListener('click', function(e) {
        if (!e.target.closest('.wishlist-btn') && !e.target.closest('.btn-view-details')) {
          const productId = this.dataset.productId;
          const variantId = this.dataset.variantId;
          const variantSku = this.dataset.variantSku;
          viewProduct(productId, variantId, variantSku);
        }
      });
    });
  }

  function toggleFilter(type, value) {
    const filterArray = state.filters[type];
    const index = filterArray.indexOf(value);
    
    if (index > -1) {
      filterArray.splice(index, 1);
    } else {
      filterArray.push(value);
    }
    
    state.page = 1;
    fetchVariants();
  }

  function removeFilter(type, value) {
    if (type === 'price') {
      state.filters.min_price = null;
      state.filters.max_price = null;
      elements.minPriceSlider.value = 0;
      elements.maxPriceSlider.value = 100;
      updatePriceDisplay();
      updatePriceTrack();
    } else if (type === 'rating') {
      state.filters.min_rating = null;
      document.querySelectorAll('.rating-option .filter-checkbox').forEach(cb => {
        cb.classList.remove('checked');
      });
    } else {
      const index = state.filters[type].indexOf(value);
      if (index > -1) {
        state.filters[type].splice(index, 1);
      }
      
      // Update UI
      document.querySelectorAll(`[data-type="${type}"][data-value="${value}"]`).forEach(el => {
        const checkbox = el.querySelector('.filter-checkbox');
        if (checkbox) checkbox.classList.remove('checked');
        const swatch = el.querySelector('.color-swatch');
        if (swatch) swatch.classList.remove('selected');
      });
    }
    
    state.page = 1;
    fetchVariants();
  }

  function clearAllFilters() {
    // Reset all filters
    state.filters = {
      category: [],
      brand: [],
      color: [],
      size: [],
      tag: [],
      min_price: null,
      max_price: null,
      min_rating: null
    };
    
    // Clear UI
    document.querySelectorAll('.filter-checkbox').forEach(cb => cb.classList.remove('checked'));
    document.querySelectorAll('.color-swatch').forEach(swatch => swatch.classList.remove('selected'));
    
    // Reset price sliders
    if (elements.minPriceSlider && elements.maxPriceSlider) {
      elements.minPriceSlider.value = 0;
      elements.maxPriceSlider.value = 100;
      updatePriceDisplay();
      updatePriceTrack();
    }
    
    state.page = 1;
    fetchVariants();
  }

  function changePage(page) {
    if (page < 1 || page > Math.ceil(state.total / state.per_page)) return;
    state.page = page;
    fetchVariants();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function viewProduct(productId, variantId, variantSku) {
    window.location.href = `/prod/${productId}?variant_id=${variantId}&variant_sku=${variantSku}`;
  }

  // ========== UI STATE FUNCTIONS ==========
  function showLoading() {
    elements.loadingContainer.classList.add('active');
    elements.productsGrid.innerHTML = '';
    elements.emptyState.classList.remove('active');
    elements.pagination.innerHTML = '';
  }

  function hideLoading() {
    elements.loadingContainer.classList.remove('active');
  }

  function showEmptyState() {
    elements.emptyState.classList.add('active');
    elements.productsGrid.innerHTML = '';
    elements.pagination.innerHTML = '';
  }

  function hideEmptyState() {
    elements.emptyState.classList.remove('active');
  }

  // ========== SEARCH & SORT HANDLERS ==========
  let searchTimeout;
  elements.searchInput.addEventListener('input', function() {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {
      state.search = this.value.trim();
      state.page = 1;
      fetchVariants();
    }, 500);
  });

  elements.sortSelect.addEventListener('change', function() {
    state.sort = this.value;
    state.page = 1;
    fetchVariants();
  });

  // Clear all filters button
  elements.clearAllFilters.addEventListener('click', clearAllFilters);

  // ========== MOBILE FILTER TOGGLE ==========
  elements.filterToggleBtn.addEventListener('click', function(e) {
    e.stopPropagation();
    openMobileFilters();
  });

  // Mobile close button
  if (elements.mobileCloseFilters) {
    elements.mobileCloseFilters.addEventListener('click', function(e) {
      e.stopPropagation();
      closeMobileFilters();
    });
  }

  elements.filterOverlay.addEventListener('click', function() {
    closeMobileFilters();
  });

  // Prevent closing when clicking inside sidebar
  elements.filtersSidebar.addEventListener('click', function(e) {
    e.stopPropagation();
  });

  function openMobileFilters() {
    elements.filtersSidebar.classList.add('active');
    elements.filterOverlay.classList.add('active');
    document.body.classList.add('no-scroll');
  }

  function closeMobileFilters() {
    elements.filtersSidebar.classList.remove('active');
    elements.filterOverlay.classList.remove('active');
    document.body.classList.remove('no-scroll');
  }

  // ========== VIEW TOGGLE (GRID/LIST) ==========
  document.querySelectorAll('.view-btn').forEach(btn => {
    btn.addEventListener('click', function() {
      const view = this.dataset.view;
      state.view = view;
      
      // Update button states
      document.querySelectorAll('.view-btn').forEach(b => b.classList.remove('active'));
      this.classList.add('active');
      
      // Update grid class
      const isMobile = window.innerWidth <= 768;
      
      if (isMobile) {
        if (view === 'list') {
          elements.productsGrid.classList.remove('mobile-grid-view');
          elements.productsGrid.classList.add('list-view');
        } else {
          elements.productsGrid.classList.remove('list-view');
          elements.productsGrid.classList.add('mobile-grid-view');
        }
      } else {
        if (view === 'list') {
          elements.productsGrid.classList.add('list-view');
          elements.productsGrid.classList.remove('mobile-grid-view');
        } else {
          elements.productsGrid.classList.remove('list-view');
          elements.productsGrid.classList.remove('mobile-grid-view');
        }
      }
    });
  });

  // ========== KEYBOARD SHORTCUTS ==========
  document.addEventListener('keydown', function(e) {
    // Close filters on Escape
    if (e.key === 'Escape') {
      if (elements.filtersSidebar.classList.contains('active')) {
        closeMobileFilters();
      }
    }
    
    // Focus search on Ctrl/Cmd + K
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
      e.preventDefault();
      elements.searchInput.focus();
    }
  });

  // ========== SCROLL TO TOP ==========
  window.addEventListener('scroll', function() {
    if (elements.scrollToTop) {
      if (window.pageYOffset > 500) {
        elements.scrollToTop.style.display = 'flex';
      } else {
        elements.scrollToTop.style.display = 'none';
      }
    }
  }, { passive: true });

  if (elements.scrollToTop) {
    elements.scrollToTop.addEventListener('click', function() {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  }

  // ========== URL PARAMETERS SYNC ==========
  function updateURLParams() {
    const params = new URLSearchParams();
    
    if (state.search) params.set('q', state.search);
    if (state.sort !== 'relevance') params.set('sort', state.sort);
    if (state.page > 1) params.set('page', state.page);
    
    state.filters.category.forEach(cat => params.append('category', cat));
    state.filters.brand.forEach(brand => params.append('brand', brand));
    state.filters.color.forEach(color => params.append('color', color));
    state.filters.size.forEach(size => params.append('size', size));
    state.filters.tag.forEach(tag => params.append('tag', tag));
    
    if (state.filters.min_price) params.set('min_price', state.filters.min_price);
    if (state.filters.max_price) params.set('max_price', state.filters.max_price);
    if (state.filters.min_rating) params.set('min_rating', state.filters.min_rating);
    
    const newURL = params.toString() ? `${window.location.pathname}?${params.toString()}` : window.location.pathname;
    window.history.pushState({}, '', newURL);
  }

  function loadFromURLParams() {
    const params = new URLSearchParams(window.location.search);
    
    state.search = params.get('q') || '';
    state.sort = params.get('sort') || 'relevance';
    state.page = parseInt(params.get('page')) || 1;
    
    state.filters.category = params.getAll('category');
    state.filters.brand = params.getAll('brand');
    state.filters.color = params.getAll('color');
    state.filters.size = params.getAll('size');
    state.filters.tag = params.getAll('tag');
    
    const minPrice = params.get('min_price');
    const maxPrice = params.get('max_price');
    const minRating = params.get('min_rating');
    
    if (minPrice) state.filters.min_price = parseFloat(minPrice);
    if (maxPrice) state.filters.max_price = parseFloat(maxPrice);
    if (minRating) state.filters.min_rating = parseFloat(minRating);
    
    // Update UI elements
    elements.searchInput.value = state.search;
    elements.sortSelect.value = state.sort;
  }

  // ========== BROWSER BACK/FORWARD SUPPORT ==========
  window.addEventListener('popstate', function() {
    loadFromURLParams();
    fetchVariants();
  });

  // ========== PERFORMANCE OPTIMIZATION ==========
  let resizeTimeout;
  window.addEventListener('resize', function() {
    clearTimeout(resizeTimeout);
    resizeTimeout = setTimeout(() => {
      // Handle responsive changes
      if (window.innerWidth > 1024) {
        closeMobileFilters();
      }
      
      // Update view based on screen size
      const isMobile = window.innerWidth <= 768;
      if (isMobile && state.view === 'grid') {
        elements.productsGrid.classList.add('mobile-grid-view');
        elements.productsGrid.classList.remove('list-view');
      } else if (isMobile && state.view === 'list') {
        elements.productsGrid.classList.add('list-view');
        elements.productsGrid.classList.remove('mobile-grid-view');
      }
    }, 250);
  }, { passive: true });

  // ========== ACCESSIBILITY IMPROVEMENTS ==========
  function announceResults() {
    const announcement = document.createElement('div');
    announcement.setAttribute('role', 'status');
    announcement.setAttribute('aria-live', 'polite');
    announcement.className = 'sr-only';
    announcement.textContent = `Showing ${state.variants.length} of ${state.total} products`;
    document.body.appendChild(announcement);
    
    setTimeout(() => announcement.remove(), 1000);
  }

  // ========== CHECK WISHLIST STATUS - FIXED ==========
  async function checkWishlistStatuses() {
    const wishlistBtns = document.querySelectorAll('.wishlist-btn');
    
    if (wishlistBtns.length === 0) return;
    
    // Check each variant individually
    const checkPromises = Array.from(wishlistBtns).map(async (btn) => {
      const variantId = btn.dataset.variantId;
      
      try {
        const response = await fetch(`/wishlist/status?variant_id=${variantId}`, {
          method: 'GET',
          headers: {
            'X-Requested-With': 'XMLHttpRequest'
          },
          credentials: 'same-origin'
        });
        
        if (response.ok) {
          const data = await response.json();
          // Check for 'wished' key as per your backend response
          if (data.ok && data.wished === true) {
            btn.classList.add('active');
            btn.textContent = '♥';
          }
        }
      } catch (error) {
        console.debug(`Could not check wishlist status for variant ${variantId}:`, error);
      }
    });
    
    // Wait for all checks to complete
    await Promise.all(checkPromises);
  }

  // ========== INITIALIZE APP ==========
  async function init() {
    try {
      // Load URL parameters first
      loadFromURLParams();
      
      // Fetch filter options
      await fetchFilters();
      
      // Update UI for pre-selected filters
      updateFilterUI();
      
      // Fetch initial variants
      await fetchVariants();
      
      // Set initial view for mobile
      const isMobile = window.innerWidth <= 768;
      if (isMobile && state.view === 'grid') {
        elements.productsGrid.classList.add('mobile-grid-view');
      }
      
      console.log('Browse page initialized successfully');
    } catch (error) {
      console.error('Error initializing browse page:', error);
      hideLoading();
      showEmptyState();
    }
  }

  function updateFilterUI() {
    // Wait for filter options to be rendered
    setTimeout(() => {
      // Update checkboxes based on state
      state.filters.category.forEach(value => {
        const option = document.querySelector(`[data-type="category"][data-value="${value}"]`);
        if (option) {
          const checkbox = option.querySelector('.filter-checkbox');
          if (checkbox) checkbox.classList.add('checked');
        }
      });
      
      state.filters.brand.forEach(value => {
        const option = document.querySelector(`[data-type="brand"][data-value="${value}"]`);
        if (option) {
          const checkbox = option.querySelector('.filter-checkbox');
          if (checkbox) checkbox.classList.add('checked');
        }
      });
      
      state.filters.color.forEach(value => {
        const option = document.querySelector(`[data-type="color"][data-value="${value}"]`);
        if (option) {
          const swatch = option.querySelector('.color-swatch');
          if (swatch) swatch.classList.add('selected');
        }
      });
      
      state.filters.size.forEach(value => {
        const option = document.querySelector(`[data-type="size"][data-value="${value}"]`);
        if (option) {
          const checkbox = option.querySelector('.filter-checkbox');
          if (checkbox) checkbox.classList.add('checked');
        }
      });
      
      state.filters.tag.forEach(value => {
        const option = document.querySelector(`[data-type="tag"][data-value="${value}"]`);
        if (option) {
          const checkbox = option.querySelector('.filter-checkbox');
          if (checkbox) checkbox.classList.add('checked');
        }
      });
      
      if (state.filters.min_rating) {
        const ratingOption = document.querySelector(`[data-type="rating"][data-value="${state.filters.min_rating}"]`);
        if (ratingOption) {
          const checkbox = ratingOption.querySelector('.filter-checkbox');
          if (checkbox) checkbox.classList.add('checked');
        }
      }
    }, 100);
  }

  // ========== START APPLICATION ==========
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // ========== EXPOSE PUBLIC API ==========
  window.BrowseApp = {
    state,
    fetchVariants,
    clearAllFilters,
    changePage,
    viewProduct,
    removeFilter
  };

})();