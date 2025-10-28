// ============================================
// ROYAL ETHNIC COLLECTION - BROWSE APP
// ============================================

class BrowseApp {
    constructor() {
        this.filters = {};
        this.currentFilters = {
            categories: [],
            brands: [],
            colors: [],
            sizes: [],
            tags: [],
            min_price: null,
            max_price: null,
            min_rating: null
        };
        this.searchQuery = '';
        this.sortBy = 'relevance';
        this.currentPage = 1;
        this.perPage = 24;
        this.totalResults = 0;
        
        this.init();
    }
    
    async init() {
        try {
            await this.loadFilters();
            await this.loadVariants();
            this.setupEventListeners();
            this.hideLoading();
        } catch (error) {
            console.error('Initialization error:', error);
            this.showError('Failed to load the collection. Please refresh the page.');
            this.hideLoading();
        }
    }
    
    // ============================================
    // API CALLS
    // ============================================
    
    async loadFilters() {
        try {
            const response = await fetch('/filters');
            if (!response.ok) throw new Error('Failed to fetch filters');
            
            this.filters = await response.json();
            this.renderFilters();
        } catch (error) {
            console.error('Error loading filters:', error);
            throw error;
        }
    }
    
    async loadVariants() {
        this.showLoading();
        
        try {
            const params = new URLSearchParams();
            
            // Search query
            if (this.searchQuery) {
                params.append('q', this.searchQuery);
            }
            
            // Filter arrays
            this.currentFilters.categories.forEach(cat => params.append('category', cat));
            this.currentFilters.brands.forEach(brand => params.append('brand', brand));
            this.currentFilters.colors.forEach(color => params.append('color', color));
            this.currentFilters.sizes.forEach(size => params.append('size', size));
            this.currentFilters.tags.forEach(tag => params.append('tag', tag));
            
            // Price range
            if (this.currentFilters.min_price !== null) {
                params.append('min_price', this.currentFilters.min_price);
            }
            if (this.currentFilters.max_price !== null) {
                params.append('max_price', this.currentFilters.max_price);
            }
            
            // Rating
            if (this.currentFilters.min_rating !== null) {
                params.append('min_rating', this.currentFilters.min_rating);
            }
            
            // Sort and pagination
            params.append('sort', this.sortBy);
            params.append('page', this.currentPage);
            params.append('per_page', this.perPage);
            
            const response = await fetch(`/variants?${params.toString()}`);
            if (!response.ok) throw new Error('Failed to fetch variants');
            
            const data = await response.json();
            this.totalResults = data.total;
            
            this.renderProducts(data.variants);
            this.renderPagination(data.page, data.per_page, data.total);
            this.updateResultsCount(data.total);
            
            // Scroll to top smoothly
            window.scrollTo({ top: 0, behavior: 'smooth' });
            
        } catch (error) {
            console.error('Error loading variants:', error);
            this.showError('Failed to load products. Please try again.');
        } finally {
            this.hideLoading();
        }
    }
    
    // ============================================
    // RENDER FILTERS
    // ============================================
    
    renderFilters() {
        // Categories
        this.renderCheckboxFilter('categoriesFilter', this.filters.categories, 'category');
        
        // Brands
        this.renderCheckboxFilter('brandsFilter', this.filters.brands, 'brand');
        
        // Colors
        this.renderColorSwatches('colorsFilter', this.filters.colors);
        
        // Sizes
        this.renderSizeOptions('sizesFilter', this.filters.sizes);
        
        // Tags
        this.renderCheckboxFilter('tagsFilter', this.filters.tags, 'tag');
        
        // Rating
        this.renderRatingOptions('ratingFilter', this.filters.rating_options);
        
        // Price range
        this.setupPriceRange(this.filters.min_price, this.filters.max_price);
    }
    
    renderCheckboxFilter(containerId, items, filterType) {
        const container = document.getElementById(containerId);
        container.innerHTML = '';
        
        items.forEach(item => {
            const option = document.createElement('div');
            option.className = 'filter-option';
            
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.id = `${filterType}-${item}`;
            checkbox.value = item;
            checkbox.dataset.filterType = filterType;
            
            const label = document.createElement('label');
            label.htmlFor = `${filterType}-${item}`;
            label.textContent = item;
            
            option.appendChild(checkbox);
            option.appendChild(label);
            container.appendChild(option);
            
            option.addEventListener('click', (e) => {
                if (e.target !== checkbox) {
                    checkbox.checked = !checkbox.checked;
                }
                this.handleFilterChange(filterType, item, checkbox.checked);
            });
        });
    }
    
    renderColorSwatches(containerId, colors) {
        const container = document.getElementById(containerId);
        container.innerHTML = '';
        container.className = 'color-swatches';
        
        colors.forEach(color => {
            const swatch = document.createElement('div');
            swatch.className = 'color-swatch';
            swatch.style.backgroundColor = this.getColorHex(color);
            swatch.dataset.color = color;
            swatch.title = color;
            
            swatch.addEventListener('click', () => {
                swatch.classList.toggle('selected');
                const isSelected = swatch.classList.contains('selected');
                this.handleFilterChange('colors', color, isSelected);
            });
            
            container.appendChild(swatch);
        });
    }
    
    renderSizeOptions(containerId, sizes) {
        const container = document.getElementById(containerId);
        container.innerHTML = '';
        container.className = 'size-options';
        
        sizes.forEach(size => {
            const option = document.createElement('div');
            option.className = 'size-option';
            option.textContent = size;
            option.dataset.size = size;
            
            option.addEventListener('click', () => {
                option.classList.toggle('selected');
                const isSelected = option.classList.contains('selected');
                this.handleFilterChange('sizes', size, isSelected);
            });
            
            container.appendChild(option);
        });
    }
    
    renderRatingOptions(containerId, ratings) {
        const container = document.getElementById(containerId);
        container.innerHTML = '';
        container.className = 'rating-options';
        
        ratings.forEach(rating => {
            const option = document.createElement('div');
            option.className = 'rating-option';
            
            const radio = document.createElement('input');
            radio.type = 'radio';
            radio.name = 'rating';
            radio.id = `rating-${rating}`;
            radio.value = rating;
            
            const stars = document.createElement('span');
            stars.className = 'stars';
            stars.innerHTML = '★'.repeat(rating) + '☆'.repeat(5 - rating);
            
            const label = document.createElement('label');
            label.htmlFor = `rating-${rating}`;
            label.textContent = `${rating} stars & above`;
            
            option.appendChild(radio);
            option.appendChild(stars);
            option.appendChild(label);
            container.appendChild(option);
            
            option.addEventListener('click', (e) => {
                if (e.target !== radio) {
                    // Clear all other radios
                    document.querySelectorAll('.rating-option').forEach(opt => {
                        opt.classList.remove('selected');
                        opt.querySelector('input').checked = false;
                    });
                    
                    radio.checked = true;
                    option.classList.add('selected');
                }
                this.currentFilters.min_rating = rating;
                this.currentPage = 1;
                this.loadVariants();
                this.updateActiveFilters();
            });
        });
    }
    
    setupPriceRange(min, max) {
        const minInput = document.getElementById('minPrice');
        const maxInput = document.getElementById('maxPrice');
        const minRange = document.getElementById('minPriceRange');
        const maxRange = document.getElementById('maxPriceRange');
        const applyBtn = document.getElementById('applyPriceFilter');
        
        minInput.placeholder = `₹ ${min}`;
        maxInput.placeholder = `₹ ${max}`;
        
        minRange.min = min;
        minRange.max = max;
        minRange.value = min;
        
        maxRange.min = min;
        maxRange.max = max;
        maxRange.value = max;
        
        minInput.value = '';
        maxInput.value = '';
        
        minRange.addEventListener('input', () => {
            minInput.value = minRange.value;
        });
        
        maxRange.addEventListener('input', () => {
            maxInput.value = maxRange.value;
        });
        
        minInput.addEventListener('input', () => {
            minRange.value = minInput.value || min;
        });
        
        maxInput.addEventListener('input', () => {
            maxRange.value = maxInput.value || max;
        });
        
        applyBtn.addEventListener('click', () => {
            this.currentFilters.min_price = minInput.value ? parseFloat(minInput.value) : null;
            this.currentFilters.max_price = maxInput.value ? parseFloat(maxInput.value) : null;
            this.currentPage = 1;
            this.loadVariants();
            this.updateActiveFilters();
        });
    }
    
    // ============================================
    // RENDER PRODUCTS
    // ============================================
    
    renderProducts(variants) {
        const grid = document.getElementById('productsGrid');
        const noResults = document.getElementById('noResults');
        
        if (variants.length === 0) {
            grid.innerHTML = '';
            noResults.style.display = 'block';
            return;
        }
        
        noResults.style.display = 'none';
        grid.innerHTML = '';
        
        variants.forEach((variant, index) => {
            const card = this.createProductCard(variant);
            card.style.animationDelay = `${index * 0.05}s`;
            grid.appendChild(card);
        });
    }
    
    createProductCard(variant) {
        const card = document.createElement('div');
        card.className = 'product-card';
        
        // Stock status
        let stockClass = 'in-stock';
        let stockText = 'In Stock';
        let stockIcon = 'fa-check-circle';
        
        if (variant.variant_stock === 0) {
            stockClass = 'out-of-stock';
            stockText = 'Out of Stock';
            stockIcon = 'fa-times-circle';
        } else if (variant.variant_stock < 5) {
            stockClass = 'low-stock';
            stockText = `Only ${variant.variant_stock} left`;
            stockIcon = 'fa-exclamation-circle';
        }
        
        // Rating stars
        const rating = variant.rating_avg || 0;
        const fullStars = Math.floor(rating);
        const hasHalfStar = rating % 1 >= 0.5;
        const emptyStars = 5 - fullStars - (hasHalfStar ? 1 : 0);
        
        let starsHtml = '★'.repeat(fullStars);
        if (hasHalfStar) starsHtml += '⯨';
        starsHtml += '☆'.repeat(emptyStars);
        
        // Image with fallback
        const imagePath = variant.image || '/static/images/placeholder.jpg';
        
        card.innerHTML = `
            <div class="product-image-wrapper">
                <img src="${imagePath}" 
                     alt="${variant.product_name}" 
                     class="product-image"
                     onerror="this.src='/static/images/placeholder.jpg'">
                ${variant.variant_stock < 5 && variant.variant_stock > 0 ? 
                    '<div class="product-badge">Limited</div>' : ''}
            </div>
            <div class="product-info">
                <div class="product-brand">${variant.brand || 'Premium Collection'}</div>
                <h3 class="product-name">${variant.product_name}</h3>
                
                <div class="product-meta">
                    ${rating > 0 ? `
                        <div class="product-rating">
                            <span class="rating-stars">${starsHtml}</span>
                            <span class="rating-value">${rating.toFixed(1)}</span>
                            <span class="rating-count">(${variant.reviews_count || 0})</span>
                        </div>
                    ` : ''}
                </div>
                
                ${variant.color ? `
                    <div class="product-variants">
                        <span class="variant-label">Color:</span>
                        <div class="variant-colors">
                            <div class="variant-color-dot" 
                                 style="background-color: ${variant.color_hex || this.getColorHex(variant.color)}"
                                 title="${variant.color}"></div>
                        </div>
                    </div>
                ` : ''}
                
                <div class="product-price">
                    <span class="current-price">₹${this.formatPrice(variant.price)}</span>
                </div>
                
                ${variant.size ? `
                    <div class="product-size">Size: <strong>${variant.size}</strong></div>
                ` : ''}
                
                <div class="product-stock ${stockClass}">
                    <i class="fas ${stockIcon}"></i>
                    ${stockText}
                </div>
            </div>
        `;
        
        return card;
    }
    
    // ============================================
    // PAGINATION
    // ============================================
    
    renderPagination(page, perPage, total) {
        const pagination = document.getElementById('pagination');
        pagination.innerHTML = '';

        const totalPages = Math.ceil(total / perPage);
        const createPageButton = (pageNum) => {
            const button = document.createElement('button');
            button.className = 'page-btn';
            button.innerText = pageNum;
            button.onclick = () => this.loadPage(pageNum);
            return button;
        };

        for (let i = 1; i <= totalPages; i++) {
            pagination.appendChild(createPageButton(i));
        }
    }

    loadPage(pageNum) {
        this.currentPage = pageNum;
        this.loadVariants();
    }

    // ============================================
    // UTILITIES
    // ============================================
    formatPrice(price) {
        return price.toFixed(2).replace(/\d(?=(\d{3})+\.)/g, '$&,');
    }
    getColorHex(colorName) {
        const colors = {
            'Red': '#FF0000',
            'Blue': '#0000FF',
            'Green': '#008000',
            'Black': '#000000',
            'White': '#FFFFFF',
            'Yellow': '#FFFF00',
            'Pink': '#FFC0CB',
        };
        return colors[colorName] || '#000000';
    }
    showLoading() {
        document.getElementById('loadingOverlay').style.display = 'flex';
    }
    hideLoading() {
        document.getElementById('loadingOverlay').style.display = 'none';
    }
    showError(message) {
        const errorDiv = document.getElementById('errorMessage');
        errorDiv.textContent = message;
        errorDiv.style.display = 'block';
    }
    updateResultsCount(total) {
        const resultsCount = document.getElementById('resultsCount');
        resultsCount.textContent = `${total} products found`;
    }
    setupEventListeners() {
        // Search input
        const searchInput = document.getElementById('searchInput');
        searchInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                this.searchQuery = searchInput.value.trim();
                this.loadVariants();
            }
        });
    }
    
    handleFilterChange(filterType, value, isSelected) { 
        const filterArray = this.currentFilters[filterType];
        if (isSelected) {
            if (!filterArray.includes(value)) {
                filterArray.push(value);
            }
        } else {
            const index = filterArray.indexOf(value);
            if (index > -1) {
                filterArray.splice(index, 1);
            }
        }
        this.currentFilters[filterType] = filterArray;
        this.loadVariants();
    }
    updateActiveFilters() {
        const activeFiltersContainer = document.getElementById('activeFilters');
        activeFiltersContainer.innerHTML = '';

        Object.keys(this.currentFilters).forEach(filterType => {
            const filterValues = this.currentFilters[filterType];
            filterValues.forEach(value => {
                const filterChip = document.createElement('div');
                filterChip.className = 'filter-chip';
                filterChip.innerText = `${filterType}: ${value}`;
                activeFiltersContainer.appendChild(filterChip);
            });
        });
    }
}
document.addEventListener('DOMContentLoaded', () => {
    new BrowseApp();
});