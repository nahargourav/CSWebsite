const categories = [
      { id: 'saree', name: 'Sarees', subtitle: 'Handloom silks & blends', image: 'https://images.unsplash.com/photo-1583391733981-e99d47e34417?auto=format&fit=crop&w=800&q=80', icon: '🪷' },
      { id: 'suiting', name: 'Suiting', subtitle: 'Fine worsted & blends', image: 'https://images.unsplash.com/photo-1507679799987-c73779587ccf?auto=format&fit=crop&w=800&q=80', icon: '👔' },
      { id: 'kurta', name: 'Kurta Cloths', subtitle: 'Cool breathable weaves', image: 'https://images.unsplash.com/photo-1622495893460-9a9f3d36f0b6?auto=format&fit=crop&w=800&q=80', icon: '🧵' },
      { id: 'shawals', name: 'Shawls', subtitle: 'Soft woolens & handwoven', image: 'https://images.unsplash.com/photo-1542576826-6f6f6f7b8e4b?auto=format&fit=crop&w=800&q=80', icon: '🧣' },
      { id: 'bedsheet', name: 'Bedsheets', subtitle: 'Premium linens & cottons', image: 'https://images.unsplash.com/photo-1505691723518-36a45b6f4e77?auto=format&fit=crop&w=800&q=80', icon: '🛏️' }
    ];

    const testimonials = [
      { name: 'Asha', text: 'They helped me choose the perfect silk for my wedding saree — the texture was unmatched.' },
      { name: 'Ramesh', text: 'Excellent suiting cloth; my tailor loved the drape. Staff are patient and honest.' },
      { name: 'Meera', text: 'I always come here for bedsheets — quality lasts for years.' }
    ];

    // ========== NAVIGATION FUNCTIONS ==========
    function gotoProduct(productId, variantId, variantSku) {
      location.href = `/prod/${productId}?variant_id=${variantId}&variant_sku=${variantSku}`;
    }

    function gotoPlaceOrder(q) {
      const qClean = q ? encodeURIComponent(q) : '';
      location.href = `/browse?q=${qClean}&sort=newest`;
    }

    // ========== WISHLIST FUNCTIONS ==========
    async function toggleWishlist(variantId, productId, button) {
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
          button.classList.toggle('active');
          button.textContent = button.classList.contains('active') ? '♥' : '♡';
        }
      } catch (error) {
        console.error('Error toggling wishlist:', error);
      }
    }

    async function checkWishlistStatus(variantId, button) {
      try {
        const response = await fetch(`/wishlist/status?variant_id=${variantId}`);
        if (response.ok) {
          const data = await response.json();
          if (data.in_wishlist) {
            button.classList.add('active');
            button.textContent = '♥';
          }
        }
      } catch (error) {
        console.error('Error checking wishlist status:', error);
      }
    }

    // ========== HERO CAROUSEL ==========
    let currentSlide = 0;
    const slides = document.querySelectorAll('.hero-slide');
    const dotsContainer = document.getElementById('heroDots');

    function renderHeroDots() {
      dotsContainer.innerHTML = '';
      slides.forEach((_, index) => {
        const dot = document.createElement('button');
        dot.className = `hero-dot ${index === currentSlide ? 'active' : ''}`;
        dot.addEventListener('click', () => {
          currentSlide = index;
          updateHeroSlide();
        });
        dotsContainer.appendChild(dot);
      });
    }

    function updateHeroSlide() {
      slides.forEach((slide, index) => {
        slide.classList.toggle('active', index === currentSlide);
      });
      renderHeroDots();
    }

    function nextHeroSlide() {
      currentSlide = (currentSlide + 1) % slides.length;
      updateHeroSlide();
    }

    renderHeroDots();
    setInterval(nextHeroSlide, 6000);

    // ========== CATEGORIES RENDERING ==========
    const categoriesGrid = document.getElementById('categoriesGrid');
    function renderCategories() {
      categoriesGrid.innerHTML = '';
      categories.forEach(cat => {
        const card = document.createElement('div');
        card.className = 'category-card';
        card.innerHTML = `
          <div class="category-image" style="background-image:url('${cat.image}')">
            <div class="category-icon">${cat.icon}</div>
            <div class="category-overlay">
              <h3 class="category-name">${cat.name}</h3>
              <p class="category-subtitle">${cat.subtitle}</p>
            </div>
          </div>
        `;
        card.addEventListener('click', () => gotoPlaceOrder(cat.id));
        categoriesGrid.appendChild(card);
      });
    }
    renderCategories();

    // ========== BESTSELLERS CAROUSEL ==========
    const bestsellersTrack = document.getElementById('bestsellersTrack');
    const bestsellersPrev = document.getElementById('bestsellersPrev');
    const bestsellersNext = document.getElementById('bestsellersNext');
    let bestsellerIndex = 0;
    let itemsPerView = 3;

    function updateItemsPerView() {
      if (window.innerWidth < 768) itemsPerView = 1;
      else if (window.innerWidth < 1024) itemsPerView = 2;
      else itemsPerView = 3;
    }

    function updateBestsellersCarousel() {
      updateItemsPerView();
      if (!bestsellersTrack || bestsellersTrack.children.length === 0) return;

      const itemWidth = bestsellersTrack.children[0].offsetWidth + 24;
      const translateX = -bestsellerIndex * itemWidth;
      bestsellersTrack.style.transform = `translateX(${translateX}px)`;

      bestsellersPrev.disabled = bestsellerIndex === 0;
      const maxIndex = Math.max(0, bestsellersTrack.children.length - itemsPerView);
      bestsellersNext.disabled = bestsellerIndex >= maxIndex;
    }

    if (bestsellersPrev && bestsellersNext) {
      bestsellersPrev.addEventListener('click', () => {
        if (bestsellerIndex > 0) {
          bestsellerIndex--;
          updateBestsellersCarousel();
        }
      });

      bestsellersNext.addEventListener('click', () => {
        const maxIndex = Math.max(0, bestsellersTrack.children.length - itemsPerView);
        if (bestsellerIndex < maxIndex) {
          bestsellerIndex++;
          updateBestsellersCarousel();
        }
      });
    }

    // Touch/swipe for bestsellers
    let startX = 0;
    let currentX = 0;
    let isSwiping = false;

    if (bestsellersTrack) {
      bestsellersTrack.addEventListener('touchstart', (e) => {
        startX = e.touches[0].clientX;
        isSwiping = true;
      });

      bestsellersTrack.addEventListener('touchmove', (e) => {
        if (!isSwiping) return;
        currentX = e.touches[0].clientX;
      });

      bestsellersTrack.addEventListener('touchend', () => {
        if (!isSwiping) return;
        isSwiping = false;

        const diff = startX - currentX;
        const threshold = 50;
        const maxIndex = Math.max(0, bestsellersTrack.children.length - itemsPerView);

        if (diff > threshold && bestsellerIndex < maxIndex) {
          bestsellerIndex++;
          updateBestsellersCarousel();
        } else if (diff < -threshold && bestsellerIndex > 0) {
          bestsellerIndex--;
          updateBestsellersCarousel();
        }
      });
    }

    // Initialize bestsellers
    document.addEventListener('DOMContentLoaded', () => {
      // Bestseller item clicks
      document.querySelectorAll('.carousel-item').forEach(item => {
        item.addEventListener('click', (e) => {
          if (!e.target.closest('.wishlist-btn') && !e.target.closest('.view-details')) {
            const productId = item.dataset.productId;
            const variantId = item.dataset.variantId;
            const variantSku = item.dataset.variantSku;
            gotoProduct(productId, variantId, variantSku);
          }
        });

        const wishlistBtn = item.querySelector('.wishlist-btn');
        if (wishlistBtn) {
          const variantId = wishlistBtn.dataset.variantId;
          const productId = wishlistBtn.dataset.productId;
          checkWishlistStatus(variantId, wishlistBtn);
          wishlistBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            toggleWishlist(variantId, productId, wishlistBtn);
          });
        }

        const viewBtn = item.querySelector('.view-details');
        if (viewBtn) {
          viewBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const productId = item.dataset.productId;
            const variantId = item.dataset.variantId;
            const variantSku = item.dataset.variantSku;
            gotoProduct(productId, variantId, variantSku);
          });
        }
      });

      updateItemsPerView();
      updateBestsellersCarousel();
    });

    window.addEventListener('resize', updateBestsellersCarousel);

    // ========== TAG SECTIONS LOADING ==========
    function loadTagSections() {
      fetch('/ajax/tag_sections')
        .then(response => {
          if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
          return response.json();
        })
        .then(data => {
          const container = document.getElementById('tagSectionsContainer');
          container.innerHTML = '';

          if (data.sections && data.sections.length > 0) {
            data.sections.forEach((section, sectionIdx) => {
              const sectionEl = document.createElement('section');
              sectionEl.className = 'tag-section';
              sectionEl.innerHTML = `
                <div class="container">
                  <div class="section-header">
                    <p class="section-subtitle">${section.tag}</p>
                    <h2 class="section-title">${section.tag} Collection</h2>
                  </div>
                  <div class="tag-carousel">
                    <button class="tag-nav prev" data-section="${sectionIdx}">‹</button>
                    <div class="tag-track" data-section="${sectionIdx}">
                      ${section.variants.map(variant => `
                        <div class="tag-item" data-product-id="${variant.product_id}" data-variant-id="${variant.variant_id}" data-variant-sku="${variant.variant_sku}">
                          <div class="tag-media" style="background-image:url('${variant.image_path || '/static/images/placeholder-420x280.png'}')">
                            <button class="wishlist-btn" data-variant-id="${variant.variant_id}" data-product-id="${variant.product_id}">♡</button>
                          </div>
                          <div class="tag-body">
                            <h4 class="tag-title">${variant.title}</h4>
                            <div class="tag-price">₹${variant.price ? variant.price : '0.00'}</div>
                          </div>
                        </div>
                      `).join('')}
                    </div>
                    <button class="tag-nav next" data-section="${sectionIdx}">›</button>
                  </div>
                </div>
              `;
              container.appendChild(sectionEl);

              // Initialize carousel for this section
              const track = sectionEl.querySelector('.tag-track');
              const prevBtn = sectionEl.querySelector('.tag-nav.prev');
              const nextBtn = sectionEl.querySelector('.tag-nav.next');
              let tagIndex = 0;
              let itemsPerTagView = 4;

              function updateTagItemsPerView() {
                if (window.innerWidth < 480) itemsPerTagView = 1;
                else if (window.innerWidth < 768) itemsPerTagView = 2;
                else if (window.innerWidth < 1200) itemsPerTagView = 3;
                else itemsPerTagView = 4;
              }
              function updateTagCarousel() {
                updateTagItemsPerView();
                if (!track || track.children.length === 0) return;

                const itemWidth = track.children[0].offsetWidth + 24;
                const translateX = -tagIndex * itemWidth;
                track.style.transform = `translateX(${translateX}px)`;

                prevBtn.disabled = tagIndex === 0;
                const maxIndex = Math.max(0, track.children.length - itemsPerTagView);
                nextBtn.disabled = tagIndex >= maxIndex;
              }
              prevBtn.addEventListener('click', () => {
                if (tagIndex > 0) {
                  tagIndex--;
                  updateTagCarousel();
                }
              });
              nextBtn.addEventListener('click', () => {
                const maxIndex = Math.max(0, track.children.length - itemsPerTagView);
                if (tagIndex < maxIndex) {
                  tagIndex++;
                  updateTagCarousel();
                }
              });
              // Touch/swipe for tag carousel
              let startX = 0;
              let currentX = 0;
              let isSwiping = false;
              track.addEventListener('touchstart', (e) => {
                startX = e.touches[0].clientX;
                isSwiping = true;
              });
              track.addEventListener('touchmove', (e) => {
                if (!isSwiping) return;
                currentX = e.touches[0].clientX;
              });
              track.addEventListener('touchend', () => {
                if (!isSwiping) return;
                isSwiping = false;

                const diff = startX - currentX;
                const threshold = 50;
                const maxIndex = Math.max(0, track.children.length - itemsPerTagView);

                if (diff > threshold && tagIndex < maxIndex) {
                  tagIndex++;
                  updateTagCarousel();
                } else if (diff < -threshold && tagIndex > 0) {
                  tagIndex--;
                  updateTagCarousel();
                }
              });
              // Initialize tag items
              sectionEl.querySelectorAll('.tag-item').forEach(item => {
                item.addEventListener('click', (e) => {
                  if (!e.target.closest('.wishlist-btn')) {
                    const productId = item.dataset.productId;
                    const variantId = item.dataset.variantId;
                    const variantSku = item.dataset.variantSku;
                    gotoProduct(productId, variantId, variantSku);
                  }
                });

                const wishlistBtn = item.querySelector('.wishlist-btn');
                if (wishlistBtn) {
                  const variantId = wishlistBtn.dataset.variantId;
                  const productId = wishlistBtn.dataset.productId;
                  checkWishlistStatus(variantId, wishlistBtn);
                  wishlistBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    toggleWishlist(variantId, productId, wishlistBtn);
                  });
                }
              });
              updateTagCarousel();
              window.addEventListener('resize', updateTagCarousel);
            });
          } else {
            container.innerHTML = '<p style="padding: 40px; text-align: center; color: var(--charcoal);">No tagged sections available.</p>';
          }
        })
        .catch(error => {
          console.error('Error loading tag sections:', error);
        });
    }
    document.addEventListener('DOMContentLoaded', loadTagSections);
    // ========== TESTIMONIALS ==========
    let currentTestimonial = 0;
    const testimonialText = document.getElementById('testimonialText');
    const testimonialAuthor = document.getElementById('testimonialAuthor');
    const prevTestimonialBtn = document.getElementById('prevTestimonial');
    const nextTestimonialBtn = document.getElementById('nextTestimonial');
    function updateTestimonial() {
      const testimonial = testimonials[currentTestimonial];
      testimonialText.textContent = testimonial.text;
      testimonialAuthor.textContent = `— ${testimonial.name}`;
    }
    prevTestimonialBtn.addEventListener('click', () => {
      currentTestimonial = (currentTestimonial - 1 + testimonials.length) % testimonials.length;
      updateTestimonial();
    });
    nextTestimonialBtn.addEventListener('click', () => {
      currentTestimonial = (currentTestimonial + 1) % testimonials.length;
      updateTestimonial();
    });
    document.addEventListener('DOMContentLoaded', updateTestimonial);