(function() {
  'use strict';

  // ========== STATE MANAGEMENT ==========
  const state = {
    variants: [],
    productImages: [],
    variantImages: {},
    currentVariantId: null,
    currentImages: [],
    currentImageIndex: 0,
    selectedColor: null,
    selectedSize: null,
    quantity: 1,
    maxQuantity: 0,
    reviewsOffset: 5,
    reviewsSort: 'latest',
    isWishlisted: false,
    touchStartX: 0,
    touchEndX: 0,
    variantCarouselIndex: 0,
    variantTouchStartX: 0,
    variantTouchEndX: 0,
    // Related products state
    relatedProducts: [],
    relatedHasMore: false,
    relatedNextCursor: null,
    relatedLoading: false,
    relatedPerPage: 12
  };

  // ========== DOM ELEMENTS ==========
  const elements = {
    mainImage: document.getElementById('mainImage'),
    thumbnailStrip: document.getElementById('thumbnailStrip'),
    prevImageBtn: document.getElementById('prevImageBtn'),
    nextImageBtn: document.getElementById('nextImageBtn'),
    mainImageContainer: document.querySelector('.main-image-container'),
    colorOptions: document.getElementById('colorOptions'),
    sizeOptions: document.getElementById('sizeOptions'),
    selectedColorName: document.getElementById('selectedColorName'),
    selectedSizeName: document.getElementById('selectedSizeName'),
    currentPrice: document.getElementById('currentPrice'),
    currentSKU: document.getElementById('currentSKU'),
    stockStatus: document.getElementById('stockStatus'),
    stockText: document.getElementById('stockText'),
    qtyInput: document.getElementById('qtyInput'),
    qtyMinus: document.getElementById('qtyMinus'),
    qtyPlus: document.getElementById('qtyPlus'),
    addToCartBtn: document.getElementById('addToCartBtn'),
    wishlistBtn: document.getElementById('wishlistBtn'),
    reviewSort: document.getElementById('reviewSort'),
    reviewsList: document.getElementById('reviewsList'),
    loadMoreReviews: document.getElementById('loadMoreReviews')
  };

  // ========== HELPER FUNCTIONS ==========
  function getVariantsPerPage() {
    const width = window.innerWidth;
    if (width <= 768) {
      return 3;
    }
    return 5;
  }

  function getSwatchWidth() {
    const width = window.innerWidth;
    if (width <= 768) {
      return 65;
    } else if (width <= 1024) {
      return 70;
    }
    return 80;
  }

  // ========== INITIALIZE ==========
  function init() {
    try {
      const variantsData = document.getElementById('variantsData');
      const productImagesData = document.getElementById('productImagesData');
      const variantImagesData = document.getElementById('variantImagesData');

      if (variantsData) state.variants = JSON.parse(variantsData.textContent);
      if (productImagesData) state.productImages = JSON.parse(productImagesData.textContent);
      if (variantImagesData) state.variantImages = JSON.parse(variantImagesData.textContent);

      const initialVariantId = window.INITIAL_VARIANT_ID;
      if (initialVariantId) {
        state.currentVariantId = initialVariantId;
      } else if (state.variants.length > 0) {
        state.currentVariantId = state.variants[0].variant_id;
      }

      const currentVariant = getCurrentVariant();
      if (currentVariant) {
        state.selectedColor = currentVariant.color;
        state.selectedSize = currentVariant.size;
      }

      console.log('Initial variant:', currentVariant);
      console.log('Total variants:', state.variants.length);

      renderVariantCarousel();
      updateImageGallery();
      updateVariantUI();
      attachEventListeners();
      checkWishlistStatus();
      initTabs();
      initTouchSwipe();
      initVariantCarouselSwipe();
      initMagnifier();
      initReviewScrollClick();
      initRelatedProducts();

      console.log('Product detail page initialized');
    } catch (error) {
      console.error('Error initializing product detail:', error);
    }
  }

  // ========== VARIANT MANAGEMENT ==========
  function getCurrentVariant() {
    return state.variants.find(v => v.variant_id === state.currentVariantId);
  }

  function findVariantByColorSize(color, size) {
    return state.variants.find(v => v.color === color && v.size === size);
  }

  // ========== VARIANT CAROUSEL ==========
  function renderVariantCarousel() {
    if (!elements.colorOptions) return;

    const carousel = document.createElement('div');
    carousel.className = 'variant-carousel';
    
    const viewport = document.createElement('div');
    viewport.className = 'variant-carousel-viewport';
    viewport.id = 'variantCarouselViewport';
    
    const track = document.createElement('div');
    track.className = 'variant-carousel-track';
    track.id = 'variantCarouselTrack';

    track.innerHTML = state.variants.map(variant => {
      const isSelected = variant.variant_id === state.currentVariantId;
      return `
        <button 
          class="color-swatch ${isSelected ? 'selected' : ''}" 
          data-variant-id="${variant.variant_id}"
          data-color="${variant.color || ''}"
          data-size="${variant.size || ''}"
          title="${variant.color || 'N/A'} - ${variant.size || 'N/A'}"
          aria-label="${variant.color || 'N/A'} ${variant.size || 'N/A'}">
          <img src="${variant.thumb || '/static/images/placeholder.png'}" alt="${variant.color}" class="color-swatch-image">
          <div class="color-swatch-color" style="background-color: ${variant.color_hex || '#cccccc'};">${variant.size || ''}</div>
          ${isSelected ? `
            <svg class="check-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="3">
              <polyline points="20 6 9 17 4 12"></polyline>
            </svg>
          ` : ''}
        </button>
      `;
    }).join('');

    viewport.appendChild(track);
    carousel.appendChild(viewport);

    const prevBtn = document.createElement('button');
    prevBtn.className = 'variant-nav-btn prev';
    prevBtn.id = 'variantPrevBtn';
    prevBtn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"></polyline></svg>';
    prevBtn.onclick = () => navigateVariantCarousel(-1);

    const nextBtn = document.createElement('button');
    nextBtn.className = 'variant-nav-btn next';
    nextBtn.id = 'variantNextBtn';
    nextBtn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"></polyline></svg>';
    nextBtn.onclick = () => navigateVariantCarousel(1);

    carousel.appendChild(prevBtn);
    carousel.appendChild(nextBtn);

    elements.colorOptions.parentNode.replaceChild(carousel, elements.colorOptions);

    setViewportWidth();

    const selectedIndex = state.variants.findIndex(v => v.variant_id === state.currentVariantId);
    if (selectedIndex !== -1) {
      const variantsPerPage = getVariantsPerPage();
      state.variantCarouselIndex = Math.floor(selectedIndex / variantsPerPage);
      updateCarouselPosition();
    }

    updateCarouselButtons();
    
    console.log('Carousel rendered. Variants per page:', getVariantsPerPage());
  }

  function setViewportWidth() {
    const viewport = document.getElementById('variantCarouselViewport');
    if (!viewport) return;

    const variantsPerPage = getVariantsPerPage();
    const swatchWidth = getSwatchWidth();
    const gap = 12;
    
    const viewportWidth = (swatchWidth * variantsPerPage) + (gap * (variantsPerPage - 1));
    viewport.style.width = `${viewportWidth}px`;
    viewport.style.maxWidth = '100%';
    viewport.style.margin = '0 auto';
    
    console.log('Viewport width set to:', viewportWidth, 'px for', variantsPerPage, 'variants');
  }

  function navigateVariantCarousel(direction) {
    const variantsPerPage = getVariantsPerPage();
    const totalPages = Math.ceil(state.variants.length / variantsPerPage);
    
    state.variantCarouselIndex += direction;

    if (state.variantCarouselIndex < 0) {
      state.variantCarouselIndex = 0;
    } else if (state.variantCarouselIndex >= totalPages) {
      state.variantCarouselIndex = totalPages - 1;
    }

    console.log('Navigate to page:', state.variantCarouselIndex, 'of', totalPages);
    
    updateCarouselPosition();
    updateCarouselButtons();
  }

  function updateCarouselPosition() {
    const track = document.getElementById('variantCarouselTrack');
    if (!track) return;

    const variantsPerPage = getVariantsPerPage();
    const swatchWidth = getSwatchWidth();
    const gap = 12;
    
    const offset = state.variantCarouselIndex * variantsPerPage * (swatchWidth + gap);
    
    track.style.transform = `translateX(-${offset}px)`;
    
    console.log('Carousel position updated. Offset:', offset, 'px');
  }

  function updateCarouselButtons() {
    const prevBtn = document.getElementById('variantPrevBtn');
    const nextBtn = document.getElementById('variantNextBtn');
    
    if (!prevBtn || !nextBtn) return;
    
    const variantsPerPage = getVariantsPerPage();
    const totalPages = Math.ceil(state.variants.length / variantsPerPage);
    
    prevBtn.disabled = state.variantCarouselIndex === 0;
    nextBtn.disabled = state.variantCarouselIndex >= totalPages - 1;
    
    console.log('Buttons updated. Current page:', state.variantCarouselIndex, 'Total pages:', totalPages);
  }

  function initVariantCarouselSwipe() {
    const viewport = document.getElementById('variantCarouselViewport');
    if (!viewport) return;

    viewport.addEventListener('touchstart', (e) => {
      state.variantTouchStartX = e.changedTouches[0].screenX;
    }, { passive: true });

    viewport.addEventListener('touchend', (e) => {
      state.variantTouchEndX = e.changedTouches[0].screenX;
      handleVariantSwipe();
    }, { passive: true });

    let isDragging = false;
    let startX = 0;

    viewport.addEventListener('mousedown', (e) => {
      isDragging = true;
      startX = e.clientX;
      viewport.style.cursor = 'grabbing';
    });

    document.addEventListener('mousemove', (e) => {
      if (!isDragging) return;
      e.preventDefault();
    });

    document.addEventListener('mouseup', (e) => {
      if (!isDragging) return;
      isDragging = false;
      viewport.style.cursor = 'grab';
      
      const endX = e.clientX;
      const diff = startX - endX;
      
      if (Math.abs(diff) > 50) {
        if (diff > 0) {
          navigateVariantCarousel(1);
        } else {
          navigateVariantCarousel(-1);
        }
      }
    });
  }

  function handleVariantSwipe() {
    const swipeThreshold = 50;
    const diff = state.variantTouchStartX - state.variantTouchEndX;

    if (Math.abs(diff) > swipeThreshold) {
      if (diff > 0) {
        navigateVariantCarousel(1);
      } else {
        navigateVariantCarousel(-1);
      }
    }
  }

  function initReviewScrollClick() {
    const ratingSummary = document.querySelector('.rating-summary');
    if (ratingSummary) {
      ratingSummary.style.cursor = 'pointer';
      ratingSummary.addEventListener('click', scrollToReviews);
    }

    const stars = document.querySelectorAll('.rating-summary .stars, .rating-summary .rating-text');
    stars.forEach(star => {
      star.style.cursor = 'pointer';
      star.addEventListener('click', scrollToReviews);
    });
  }

  function scrollToReviews(e) {
    e.preventDefault();
    const reviewsTab = document.querySelector('[data-tab="reviews"]');
    const reviewsSection = document.getElementById('reviewsTab');
    
    if (reviewsTab && reviewsSection) {
      document.querySelectorAll('.tab-header').forEach(h => h.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
      
      reviewsTab.classList.add('active');
      reviewsSection.classList.add('active');
      
      setTimeout(() => {
        reviewsSection.scrollIntoView({ 
          behavior: 'smooth', 
          block: 'start' 
        });
      }, 100);
    }
  }

  function updateVariantUI() {
    const variant = getCurrentVariant();
    if (!variant) return;

    if (elements.currentPrice) {
      elements.currentPrice.textContent = `₹${parseFloat(variant.price).toFixed(2)}`;
    }

    if (elements.currentSKU) {
      elements.currentSKU.textContent = variant.sku || 'N/A';
    }

    if (elements.selectedColorName) {
      elements.selectedColorName.textContent = variant.color || 'N/A';
    }
    if (elements.selectedSizeName) {
      elements.selectedSizeName.textContent = variant.size || 'N/A';
    }

    state.maxQuantity = parseInt(variant.stock_count) || 0;

    if (elements.qtyInput) {
      elements.qtyInput.max = state.maxQuantity;
      if (state.quantity > state.maxQuantity) {
        state.quantity = Math.max(1, state.maxQuantity);
        elements.qtyInput.value = state.quantity;
      }
    }

    updateAddToCartButton();

    if (elements.wishlistBtn) {
      elements.wishlistBtn.dataset.variantId = variant.variant_id;
    }

    updateURL(variant);
  }

  function updateURL(variant) {
    if (!variant) return;
    
    const url = new URL(window.location);
    url.searchParams.set('variant_id', variant.variant_id);
    if (variant.sku) {
      url.searchParams.set('variant_sku', variant.sku);
    }
    window.history.replaceState({}, '', url);
  }

  function updateAddToCartButton() {
    if (!elements.addToCartBtn) return;

    if (state.maxQuantity <= 0) {
      elements.addToCartBtn.disabled = true;
      elements.addToCartBtn.querySelector('span').textContent = 'Out of Stock';
    } else {
      elements.addToCartBtn.disabled = false;
      elements.addToCartBtn.querySelector('span').textContent = 'Add to Cart';
    }
  }

  // ========== RELATED PRODUCTS SECTION ==========
  function initRelatedProducts() {
    const variant = getCurrentVariant();
    if (!variant) return;

    // Create related products section after tabs
    const tabsSection = document.querySelector('.tabs-section');
    if (!tabsSection) return;

    const relatedSection = document.createElement('section');
    relatedSection.className = 'related-products-section';
    relatedSection.id = 'relatedProductsSection';
    relatedSection.innerHTML = `
      <div class="related-products-header">
        <h2 class="related-products-title">You May Also Like</h2>
        <p class="related-products-subtitle">Handpicked recommendations just for you</p>
      </div>
      <div class="related-products-grid" id="relatedProductsGrid"></div>
      <div class="related-products-loader" id="relatedProductsLoader">
        <div class="loader-spinner"></div>
        <p>Loading more products...</p>
      </div>
    `;

    tabsSection.parentNode.insertBefore(relatedSection, tabsSection.nextSibling);

    // Load first batch
    loadRelatedProducts(variant.variant_id);

    // Setup infinite scroll
    setupRelatedProductsScroll();
  }

  async function loadRelatedProducts(variantId, cursor = null) {
    if (state.relatedLoading) return;

    state.relatedLoading = true;
    const loader = document.getElementById('relatedProductsLoader');
    if (loader) loader.style.display = 'flex';

    try {
      let url = `/api/recommendations?variant_id=${variantId}&per_page=${state.relatedPerPage}`;
      
      if (cursor && cursor.last_score !== null && cursor.last_variant_id) {
        url += `&last_score=${cursor.last_score}&last_variant_id=${cursor.last_variant_id}`;
      }

      const response = await fetch(url);
      const data = await response.json();

      if (response.ok) {
        state.relatedProducts = [...state.relatedProducts, ...data.variants];
        state.relatedHasMore = data.has_more;
        state.relatedNextCursor = data.next_cursor;

        renderRelatedProducts(data.variants);

        console.log('Loaded', data.returned, 'related products. Has more:', data.has_more);
      } else {
        console.error('Error loading related products:', data.message);
      }
    } catch (error) {
      console.error('Error fetching related products:', error);
    } finally {
      state.relatedLoading = false;
      if (loader) {
        loader.style.display = state.relatedHasMore ? 'none' : 'none';
      }
    }
  }

  function renderRelatedProducts(products) {
    const grid = document.getElementById('relatedProductsGrid');
    if (!grid) return;

    products.forEach(product => {
      const card = createRelatedProductCard(product);
      grid.appendChild(card);
    });
  }

  function createRelatedProductCard(product) {
    const card = document.createElement('div');
    card.className = 'related-product-card fade-in';
    
    const price = parseFloat(product.price || 0).toFixed(2);
    const rating = parseFloat(product.rating_avg || 0);
    const reviewCount = parseInt(product.reviews_count || 0);
    const stars = generateStars(rating);

    card.innerHTML = `
      <a href="/prod/${product.product_id}?variant_id=${product.variant_id}" class="related-product-link">
        <div class="related-product-image-wrapper">
          <img src="${product.image || '/static/images/placeholder.png'}" alt="${product.product_name}" class="related-product-image">
          ${product.variant_stock <= 0 ? '<div class="related-product-badge out-of-stock">Out of Stock</div>' : ''}
          ${product.variant_stock > 0 && product.variant_stock <= 5 ? '<div class="related-product-badge low-stock">Only ' + product.variant_stock + ' Left</div>' : ''}
        </div>
        <div class="related-product-info">
          ${product.brand ? `<div class="related-product-brand">${product.brand}</div>` : ''}
          <h3 class="related-product-name">${product.product_name}</h3>
          ${product.color || product.size ? `<div class="related-product-variant">${product.color || ''} ${product.size ? '• ' + product.size : ''}</div>` : ''}
          <div class="related-product-rating">
            ${stars}
            ${reviewCount > 0 ? `<span class="related-product-review-count">(${reviewCount})</span>` : ''}
          </div>
          <div class="related-product-price">₹${price}</div>
        </div>
      </a>
    `;

    return card;
  }

  function generateStars(rating) {
    const fullStars = Math.floor(rating);
    const halfStar = rating % 1 >= 0.5;
    let html = '';

    for (let i = 0; i < 5; i++) {
      if (i < fullStars) {
        html += '<svg class="star filled" width="14" height="14" viewBox="0 0 24 24"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg>';
      } else if (i === fullStars && halfStar) {
        html += '<svg class="star half" width="14" height="14" viewBox="0 0 24 24"><defs><linearGradient id="half"><stop offset="50%" stop-color="#fbbf24"/><stop offset="50%" stop-color="#e5e7eb"/></linearGradient></defs><path fill="url(#half)" d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg>';
      } else {
        html += '<svg class="star" width="14" height="14" viewBox="0 0 24 24"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg>';
      }
    }

    return html;
  }

  function setupRelatedProductsScroll() {
    const handleScroll = () => {
      const section = document.getElementById('relatedProductsSection');
      if (!section || !state.relatedHasMore || state.relatedLoading) return;

      const sectionRect = section.getBoundingClientRect();
      const windowHeight = window.innerHeight;

      // Trigger load when section is 200px from bottom of viewport
      if (sectionRect.bottom - windowHeight < 200) {
        const variant = getCurrentVariant();
        if (variant && state.relatedNextCursor) {
          loadRelatedProducts(variant.variant_id, state.relatedNextCursor);
        }
      }
    };

    window.addEventListener('scroll', handleScroll, { passive: true });
  }

  // ========== IMAGE GALLERY ==========
  function updateImageGallery() {
    const variant = getCurrentVariant();
    if (variant && state.variantImages[variant.variant_id]) {
      state.currentImages = state.variantImages[variant.variant_id];
    } else if (state.productImages.length > 0) {
      state.currentImages = state.productImages;
    } else {
      state.currentImages = [{ path: variant?.thumb || '/static/images/placeholder.png' }];
    }

    state.currentImageIndex = 0;
    updateMainImage();
    renderThumbnails();
  }

  function updateMainImage() {
    if (!elements.mainImage || state.currentImages.length === 0) return;

    const currentImage = state.currentImages[state.currentImageIndex];
    elements.mainImage.src = currentImage.path || '/static/images/placeholder.png';
    elements.mainImage.alt = currentImage.alt_text || 'Product image';

    const magnifierImg = document.querySelector('.magnifier-window img');
    if (magnifierImg) {
      magnifierImg.src = currentImage.path || '/static/images/placeholder.png';
    }

    document.querySelectorAll('.thumbnail').forEach((thumb, index) => {
      thumb.classList.toggle('active', index === state.currentImageIndex);
    });
  }

  function renderThumbnails() {
    if (!elements.thumbnailStrip) return;

    elements.thumbnailStrip.innerHTML = state.currentImages.map((img, index) => `
      <div class="thumbnail ${index === 0 ? 'active' : ''}" data-index="${index}">
        <img src="${img.path || '/static/images/placeholder.png'}" alt="Thumbnail ${index + 1}">
      </div>
    `).join('');

    document.querySelectorAll('.thumbnail').forEach((thumb, index) => {
      thumb.addEventListener('click', () => {
        state.currentImageIndex = index;
        updateMainImage();
      });
    });
  }

  function navigateImage(direction) {
    if (state.currentImages.length <= 1) return;

    state.currentImageIndex += direction;
    
    if (state.currentImageIndex < 0) {
      state.currentImageIndex = state.currentImages.length - 1;
    } else if (state.currentImageIndex >= state.currentImages.length) {
      state.currentImageIndex = 0;
    }

    updateMainImage();
  }

  // ========== MAGNIFIER WINDOW ==========
  function initMagnifier() {
    const container = elements.mainImageContainer;
    if (!container || window.innerWidth <= 1024) return;

    const magnifier = document.createElement('div');
    magnifier.className = 'magnifier-window';
    const magnifierImg = document.createElement('img');
    magnifierImg.src = elements.mainImage.src;
    magnifier.appendChild(magnifierImg);
    container.appendChild(magnifier);

    const zoomLevel = 2.5;
    const magnifierSize = 200;

    let isOverWishlist = false;

    container.addEventListener('mousemove', (e) => {
      const wishlistBtn = container.querySelector('.wishlist-fab');
      if (wishlistBtn) {
        const rect = wishlistBtn.getBoundingClientRect();
        const x = e.clientX;
        const y = e.clientY;
        isOverWishlist = (x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom);
      }

      if (isOverWishlist) {
        magnifier.style.display = 'none';
        return;
      }

      magnifier.style.display = 'block';

      const containerRect = container.getBoundingClientRect();
      const x = e.clientX - containerRect.left;
      const y = e.clientY - containerRect.top;

      magnifier.style.left = `${x - magnifierSize / 2}px`;
      magnifier.style.top = `${y - magnifierSize / 2}px`;

      const imgWidth = elements.mainImage.width * zoomLevel;
      const imgHeight = elements.mainImage.height * zoomLevel;

      const bgX = (x / containerRect.width) * imgWidth - magnifierSize / 2;
      const bgY = (y / containerRect.height) * imgHeight - magnifierSize / 2;

      magnifierImg.style.width = `${imgWidth}px`;
      magnifierImg.style.height = `${imgHeight}px`;
      magnifierImg.style.left = `-${bgX}px`;
      magnifierImg.style.top = `-${bgY}px`;
    });

    container.addEventListener('mouseleave', () => {
      magnifier.style.display = 'none';
      isOverWishlist = false;
    });

    container.addEventListener('mouseenter', () => {
      if (!isOverWishlist) {
        magnifier.style.display = 'block';
      }
    });
  }

  // ========== FULLSCREEN IMAGE ==========
  function openFullscreen() {
    const currentImage = state.currentImages[state.currentImageIndex];
    if (!currentImage) return;

    const modal = document.createElement('div');
    modal.className = 'fullscreen-modal active';
    modal.innerHTML = `
      <button class="fullscreen-close" aria-label="Close fullscreen">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="18" y1="6" x2="6" y2="18"></line>
          <line x1="6" y1="6" x2="18" y2="18"></line>
        </svg>
      </button>
      <img src="${currentImage.path}" alt="${currentImage.alt_text || 'Product image'}">
    `;

    document.body.appendChild(modal);
    document.body.style.overflow = 'hidden';

    const closeBtn = modal.querySelector('.fullscreen-close');
    closeBtn.addEventListener('click', () => closeFullscreen(modal));
    
    modal.addEventListener('click', (e) => {
      if (e.target === modal) closeFullscreen(modal);
    });

    document.addEventListener('keydown', function escHandler(e) {
      if (e.key === 'Escape') {
        closeFullscreen(modal);
        document.removeEventListener('keydown', escHandler);
      }
    });
  }

  function closeFullscreen(modal) {
    modal.classList.remove('active');
    document.body.style.overflow = '';
    setTimeout(() => modal.remove(), 300);
  }

  // ========== TOUCH SWIPE ==========
  function initTouchSwipe() {
    const container = elements.mainImageContainer;
    if (!container) return;

    container.addEventListener('touchstart', (e) => {
      state.touchStartX = e.changedTouches[0].screenX;
    }, { passive: true });

    container.addEventListener('touchend', (e) => {
      state.touchEndX = e.changedTouches[0].screenX;
      handleSwipe();
    }, { passive: true });
  }

  function handleSwipe() {
    const swipeThreshold = 50;
    const diff = state.touchStartX - state.touchEndX;

    if (Math.abs(diff) > swipeThreshold) {
      if (diff > 0) {
        navigateImage(1);
      } else {
        navigateImage(-1);
      }
    }
  }

  // ========== VARIANT SELECTION ==========
  function selectVariant(variantId) {
    const variant = state.variants.find(v => v.variant_id === variantId);
    if (!variant) return;

    state.currentVariantId = variantId;
    state.selectedColor = variant.color;
    state.selectedSize = variant.size;

    document.querySelectorAll('.color-swatch').forEach(swatch => {
      const swatchVariantId = parseInt(swatch.dataset.variantId);
      const isSelected = swatchVariantId === variantId;
      swatch.classList.toggle('selected', isSelected);
      
      const existingCheck = swatch.querySelector('.check-icon');
      if (existingCheck) existingCheck.remove();
      
      if (isSelected) {
        swatch.innerHTML += `
          <svg class="check-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="3">
            <polyline points="20 6 9 17 4 12"></polyline>
          </svg>
        `;
      }
    });

    if (elements.sizeOptions) {
      document.querySelectorAll('.size-button').forEach(btn => {
        btn.classList.toggle('selected', btn.dataset.size === variant.size);
      });
    }

    updateVariantUI();
    updateImageGallery();
    checkWishlistStatus();
  }

  function selectSize(size) {
    state.selectedSize = size;

    document.querySelectorAll('.size-button').forEach(btn => {
      btn.classList.toggle('selected', btn.dataset.size === size);
    });

    if (elements.selectedSizeName) {
      elements.selectedSizeName.textContent = size;
    }

    const newVariant = findVariantByColorSize(state.selectedColor, size);
    if (newVariant) {
      selectVariant(newVariant.variant_id);
    }
  }

  // ========== QUANTITY MANAGEMENT ==========
  function updateQuantity(change) {
    const newQty = state.quantity + change;
    
    if (newQty >= 1 && newQty <= state.maxQuantity) {
      state.quantity = newQty;
      if (elements.qtyInput) {
        elements.qtyInput.value = state.quantity;
      }
    }

    if (elements.qtyMinus) {
      elements.qtyMinus.disabled = state.quantity <= 1;
    }
    if (elements.qtyPlus) {
      elements.qtyPlus.disabled = state.quantity >= state.maxQuantity;
    }
  }

  // ========== CART OPERATIONS ==========
  async function addToCart() {
    const variant = getCurrentVariant();
    if (!variant || state.maxQuantity <= 0) return;

    if (state.quantity > state.maxQuantity) {
      showNotification('Cannot add more than available stock', 'error');
      state.quantity = state.maxQuantity;
      elements.qtyInput.value = state.quantity;
      return;
    }

    elements.addToCartBtn.disabled = true;
    const originalText = elements.addToCartBtn.querySelector('span').textContent;
    elements.addToCartBtn.querySelector('span').textContent = 'Adding...';

    try {
      const formData = new FormData();
      formData.append('product_id', window.PRODUCT_ID);
      formData.append('variant_id', variant.variant_id);
      formData.append('qty', state.quantity);

      const response = await fetch('/cart/add', {
        method: 'POST',
        headers: {
          'X-Requested-With': 'XMLHttpRequest'
        },
        body: formData
      });

      const data = await response.json();

      if (response.ok && data.ok) {
        showNotification('Added to cart successfully!', 'success');
        updateCartCount(data.cart_count);

        state.quantity = 1;
        if (elements.qtyInput) elements.qtyInput.value = 1;
        updateQuantity(0);

      } else if (response.status === 401) {
        showNotification(data.message || 'Please login to add items to cart', 'warning');
        setTimeout(() => {
          window.location.href = data.redirect_url || '/login';
        }, 1500);
      } else {
        showNotification(data.message || 'Failed to add to cart', 'error');
      }

    } catch (error) {
      console.error('Error adding to cart:', error);
      showNotification('Something went wrong. Please try again.', 'error');
    } finally {
      elements.addToCartBtn.disabled = false;
      elements.addToCartBtn.querySelector('span').textContent = originalText;
    }
  }

  // ========== WISHLIST OPERATIONS ==========
  async function checkWishlistStatus() {
    const variant = getCurrentVariant();
    if (!variant || !elements.wishlistBtn) return;

    try {
      const response = await fetch(`/wishlist/status?variant_id=${variant.variant_id}`, {
        headers: {
          'X-Requested-With': 'XMLHttpRequest'
        }
      });

      if (response.ok) {
        const data = await response.json();
        if (data.ok && data.wished) {
          state.isWishlisted = true;
          elements.wishlistBtn.classList.add('active');
        } else {
          state.isWishlisted = false;
          elements.wishlistBtn.classList.remove('active');
        }
      }
    } catch (error) {
      console.error('Error checking wishlist status:', error);
    }
  }

  async function toggleWishlist() {
    const variant = getCurrentVariant();
    if (!variant || !elements.wishlistBtn) return;

    try {
      const formData = new FormData();
      formData.append('product_id', window.PRODUCT_ID);
      formData.append('variant_id', variant.variant_id);

      const response = await fetch('/wishlist/toggle', {
        method: 'POST',
        headers: {
          'X-Requested-With': 'XMLHttpRequest'
        },
        body: formData
      });

      if (response.status === 401) {
        showNotification('Please login to manage wishlist', 'warning');
        setTimeout(() => {
          window.location.href = '/login';
        }, 1500);
        return;
      }

      const data = await response.json();

      if (data.ok) {
        state.isWishlisted = data.action === 'added';
        elements.wishlistBtn.classList.toggle('active', state.isWishlisted);
        
        const message = state.isWishlisted ? 'Added to wishlist' : 'Removed from wishlist';
        showNotification(message, 'success');

        if (data.wishlist_count !== undefined) {
          updateWishlistCount(data.wishlist_count);
        }
      } else {
        showNotification(data.message || 'Failed to update wishlist', 'error');
      }

    } catch (error) {
      console.error('Error toggling wishlist:', error);
      showNotification('Something went wrong. Please try again.', 'error');
    }
  }

  // ========== REVIEWS ==========
  async function loadReviews(sort = 'latest', offset = 0) {
    try {
      const response = await fetch(`/prod/${window.PRODUCT_ID}/reviews_ajax?sort=${sort}&offset=${offset}&limit=5`);
      const data = await response.json();

      if (data.ok) {
        if (offset === 0) {
          renderReviews(data.reviews);
        } else {
          appendReviews(data.reviews);
        }

        state.reviewsOffset = offset + data.reviews.length;

        if (elements.loadMoreReviews) {
          if (state.reviewsOffset >= data.total_reviews) {
            elements.loadMoreReviews.style.display = 'none';
          } else {
            elements.loadMoreReviews.style.display = 'block';
          }
        }
      }
    } catch (error) {
      console.error('Error loading reviews:', error);
    }
  }

  function renderReviews(reviews) {
    if (!elements.reviewsList) return;

    if (reviews.length === 0) {
      elements.reviewsList.innerHTML = '<p style="text-align:center;color:rgba(45,45,45,0.5);padding:40px 0;">No reviews yet. Be the first to review!</p>';
      return;
    }

    elements.reviewsList.innerHTML = reviews.map(review => createReviewHTML(review)).join('');
  }

  function appendReviews(reviews) {
    if (!elements.reviewsList) return;

    const fragment = document.createDocumentFragment();
    reviews.forEach(review => {
      const div = document.createElement('div');
      div.innerHTML = createReviewHTML(review);
      fragment.appendChild(div.firstElementChild);
    });

    elements.reviewsList.appendChild(fragment);
  }

  function createReviewHTML(review) {
    const stars = Array(5).fill(0).map((_, i) => {
      const filled = i < review.rating ? 'filled' : '';
      return `<svg class="star ${filled}" width="16" height="16" viewBox="0 0 24 24">
        <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/>
      </svg>`;
    }).join('');

    return `
      <div class="review-card fade-in">
        <div class="review-header">
          <div class="reviewer-info">
            <div class="reviewer-avatar">${(review.customer_name[0] || 'A').toUpperCase()}</div>
            <div>
              <div class="reviewer-name">${review.customer_name}</div>
              <div class="review-date">${review.created_at_str}</div>
            </div>
          </div>
          <div class="review-rating">${stars}</div>
        </div>
        ${review.title ? `<h4 class="review-title">${review.title}</h4>` : ''}
        ${review.body ? `<p class="review-body">${review.body}</p>` : ''}
      </div>
    `;
  }

  // ========== TABS ==========
  function initTabs() {
    const tabHeaders = document.querySelectorAll('.tab-header');
    const tabContents = document.querySelectorAll('.tab-content');

    tabHeaders.forEach(header => {
      header.addEventListener('click', () => {
        const tabName = header.dataset.tab;

        tabHeaders.forEach(h => h.classList.remove('active'));
        tabContents.forEach(c => c.classList.remove('active'));

        header.classList.add('active');
        document.getElementById(`${tabName}Tab`).classList.add('active');
      });
    });
  }

  // ========== EVENT LISTENERS ==========
  function attachEventListeners() {
    if (elements.prevImageBtn) {
      elements.prevImageBtn.addEventListener('click', () => navigateImage(-1));
    }
    if (elements.nextImageBtn) {
      elements.nextImageBtn.addEventListener('click', () => navigateImage(1));
    }

    let lastTap = 0;
    if (elements.mainImageContainer) {
      elements.mainImageContainer.addEventListener('touchend', (e) => {
        const currentTime = new Date().getTime();
        const tapLength = currentTime - lastTap;
        if (tapLength < 500 && tapLength > 0) {
          openFullscreen();
        }
        lastTap = currentTime;
      });

      elements.mainImageContainer.addEventListener('dblclick', (e) => {
        if (!e.target.closest('.img-nav-btn') && !e.target.closest('.wishlist-fab')) {
          openFullscreen();
        }
      });
    }

    document.addEventListener('click', (e) => {
      const swatch = e.target.closest('.color-swatch');
      if (swatch) {
        const variantId = parseInt(swatch.dataset.variantId);
        selectVariant(variantId);
      }
    });

    if (elements.sizeOptions) {
      elements.sizeOptions.addEventListener('click', (e) => {
        const btn = e.target.closest('.size-button');
        if (btn && !btn.disabled) {
          selectSize(btn.dataset.size);
        }
      });
    }

    if (elements.qtyMinus) {
      elements.qtyMinus.addEventListener('click', () => updateQuantity(-1));
    }
    if (elements.qtyPlus) {
      elements.qtyPlus.addEventListener('click', () => updateQuantity(1));
    }
    if (elements.qtyInput) {
      elements.qtyInput.addEventListener('change', (e) => {
        let value = parseInt(e.target.value);
        if (isNaN(value) || value < 1) value = 1;
        if (value > state.maxQuantity) {
          showNotification('Cannot exceed available stock', 'error');
          value = state.maxQuantity;
        }
        state.quantity = value;
        e.target.value = value;
        updateQuantity(0);
      });
    }

    if (elements.addToCartBtn) {
      elements.addToCartBtn.addEventListener('click', addToCart);
    }

    if (elements.wishlistBtn) {
      elements.wishlistBtn.addEventListener('click', toggleWishlist);
    }

    if (elements.reviewSort) {
      elements.reviewSort.addEventListener('change', (e) => {
        state.reviewsSort = e.target.value;
        state.reviewsOffset = 0;
        loadReviews(state.reviewsSort, 0);
      });
    }

    if (elements.loadMoreReviews) {
      elements.loadMoreReviews.addEventListener('click', () => {
        loadReviews(state.reviewsSort, state.reviewsOffset);
      });
    }

    document.addEventListener('keydown', (e) => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

      if (e.key === 'ArrowLeft') {
        navigateImage(-1);
      } else if (e.key === 'ArrowRight') {
        navigateImage(1);
      }
    });

    let resizeTimeout;
    window.addEventListener('resize', function() {
      clearTimeout(resizeTimeout);
      resizeTimeout = setTimeout(() => {
        console.log('Window resized. Recalculating carousel...');
        setViewportWidth();
        updateCarouselPosition();
        updateCarouselButtons();
      }, 250);
    });
  }

  // ========== UTILITY FUNCTIONS ==========
  function updateCartCount(count) {
    const cartCountElements = document.querySelectorAll('[data-cart-count]');
    cartCountElements.forEach(el => {
      el.textContent = count;
      el.dataset.cartCount = count;
    });
  }

  function updateWishlistCount(count) {
    const wishlistCountElements = document.querySelectorAll('[data-wishlist-count]');
    wishlistCountElements.forEach(el => {
      el.textContent = count;
      el.dataset.wishlistCount = count;
    });
  }

  function showNotification(message, type = 'info') {
    const existing = document.querySelector('.notification-toast');
    if (existing) existing.remove();

    const notification = document.createElement('div');
    notification.className = `notification-toast notification-${type}`;
    notification.textContent = message;

    notification.style.cssText = `
      position: fixed;
      bottom: 24px;
      right: 24px;
      padding: 16px 24px;
      background: ${type === 'success' ? '#10b981' : type === 'error' ? '#ef4444' : type === 'warning' ? '#f59e0b' : '#3b82f6'};
      color: white;
      border-radius: 12px;
      box-shadow: 0 8px 24px rgba(0,0,0,0.15);
      font-weight: 600;
      font-size: 15px;
      z-index: 10000;
      animation: slideInUp 0.3s ease;
      max-width: 90vw;
    `;

    document.body.appendChild(notification);

    setTimeout(() => {
      notification.style.animation = 'slideOutDown 0.3s ease';
      setTimeout(() => notification.remove(), 300);
    }, 3000);
  }

  const style = document.createElement('style');
  style.textContent = `
    @keyframes slideInUp {
      from {
        transform: translateY(100%);
        opacity: 0;
      }
      to {
        transform: translateY(0);
        opacity: 1;
      }
    }
    @keyframes slideOutDown {
      from {
        transform: translateY(0);
        opacity: 1;
      }
      to {
        transform: translateY(100%);
        opacity: 0;
      }
    }

    /* Related Products Styles */
    .related-products-section {
      max-width: 1400px;
      margin: 60px auto 0;
      padding: 0 40px 0px;
    }

    .related-products-header {
      text-align: center;
      margin-bottom: 48px;
    }

    .related-products-title {
      font-family: var(--font-heading);
      font-size: 36px;
      font-weight: 600;
      color: var(--deep-navy);
      margin: 0 0 12px 0;
    }

    .related-products-subtitle {
      font-size: 16px;
      color: rgba(45, 45, 45, 0.6);
      margin: 0;
    }

    .related-products-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
      gap: 32px;
      margin-bottom: 40px;
    }

    .related-product-card {
      background: white;
      border-radius: 16px;
      overflow: hidden;
      box-shadow: var(--shadow-sm);
      transition: var(--transition);
    }

    .related-product-card:hover {
      transform: translateY(-8px);
      box-shadow: var(--shadow-lg);
    }

    .related-product-link {
      text-decoration: none;
      color: inherit;
      display: block;
    }

    .related-product-image-wrapper {
      position: relative;
      aspect-ratio: 3/4;
      overflow: hidden;
      background: #f5f5f5;
    }

    .related-product-image {
      width: 100%;
      height: 100%;
      object-fit: cover;
      transition: transform 0.5s ease;
    }

    .related-product-card:hover .related-product-image {
      transform: scale(1.1);
    }

    .related-product-badge {
      position: absolute;
      top: 12px;
      right: 12px;
      padding: 6px 12px;
      border-radius: 8px;
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }

    .related-product-badge.out-of-stock {
      background: rgba(239, 68, 68, 0.9);
      color: white;
    }

    .related-product-badge.low-stock {
      background: rgba(245, 158, 11, 0.9);
      color: white;
    }

    .related-product-info {
      padding: 20px;
    }

    .related-product-brand {
      font-size: 12px;
      font-weight: 700;
      color: var(--royal-gold);
      text-transform: uppercase;
      letter-spacing: 1px;
      margin-bottom: 8px;
    }

    .related-product-name {
      font-size: 18px;
      font-weight: 600;
      color: var(--charcoal);
      margin: 0 0 8px 0;
      line-height: 1.4;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }

    .related-product-variant {
      font-size: 14px;
      color: rgba(45, 45, 45, 0.6);
      margin-bottom: 12px;
    }

    .related-product-rating {
      display: flex;
      align-items: center;
      gap: 6px;
      margin-bottom: 12px;
    }

    .related-product-review-count {
      font-size: 13px;
      color: rgba(45, 45, 45, 0.6);
    }

    .related-product-price {
      font-family: var(--font-heading);
      font-size: 24px;
      font-weight: 700;
      color: var(--royal-gold);
    }

    .related-products-loader {
      display: none;
      flex-direction: column;
      align-items: center;
      gap: 16px;
      padding: 40px;
      color: rgba(45, 45, 45, 0.6);
    }

    .loader-spinner {
      width: 48px;
      height: 48px;
      border: 4px solid rgba(212, 175, 55, 0.2);
      border-top-color: var(--royal-gold);
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
    }

    @keyframes spin {
      to { transform: rotate(360deg); }
    }

    @media (max-width: 1024px) {
      .related-products-section {
        padding: 0 20px 60px;
      }

      .related-products-grid {
        grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
        gap: 24px;
      }

      .related-products-title {
        font-size: 28px;
      }
    }

    @media (max-width: 768px) {
      .related-products-grid {
        grid-template-columns: repeat(2, 1fr);
        gap: 16px;
      }

      .related-products-title {
        font-size: 24px;
      }

      .related-product-info {
        padding: 16px;
      }

      .related-product-name {
        font-size: 16px;
      }

      .related-product-price {
        font-size: 20px;
      }
    }
  `;
  document.head.appendChild(style);

  // ========== INITIALIZE ON DOM READY ==========
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // ========== EXPOSE PUBLIC API ==========
  window.ProductDetail = {
    state,
    selectVariant,
    selectSize,
    addToCart,
    toggleWishlist,
    updateQuantity,
    navigateVariantCarousel
  };

})();