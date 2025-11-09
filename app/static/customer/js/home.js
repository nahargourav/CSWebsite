const categories = [
  { id: 'sarees', name: 'Sarees', subtitle: 'Handloom silks & blends', image: 'https://pub-7c7bd23b07634721bd3abfebbc76c007.r2.dev/Category/category-sarees.jpg'},
  { id: 'suiting', name: 'Suiting & Shirting', subtitle: 'Fine worsted & blends', image: 'https://pub-7c7bd23b07634721bd3abfebbc76c007.r2.dev/Category/category-suiting.jpg'},
  { id: 'kurta', name: 'Kurta', subtitle: 'Cool breathable weaves', image: 'https://pub-7c7bd23b07634721bd3abfebbc76c007.r2.dev/Category/category-kurta-men.jpg'},
  { id: 'salwar', name: 'Salwar Suit', subtitle: 'Traditional & modern', image: 'https://pub-7c7bd23b07634721bd3abfebbc76c007.r2.dev/Category/category-salwar-suit.jpg'},
  { id: 'shawls', name: 'Shawls & Stoles', subtitle: 'Soft woolens & handwoven', image: 'https://pub-7c7bd23b07634721bd3abfebbc76c007.r2.dev/Category/category-shawls-stoles.jpg' },
  { id: 'bedsheets', name: 'Bedsheets', subtitle: 'Premium linens & cottons', image: 'https://pub-7c7bd23b07634721bd3abfebbc76c007.r2.dev/Category/category-bedsheets.jpg' }
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
      if (data.ok && (data.in_wishlist || data.wished)) {
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
const heroSection = document.querySelector('.hero-section');
let heroAutoPlayInterval = null;

function renderHeroDots() {
  if (!dotsContainer) return;
  dotsContainer.innerHTML = '';
  slides.forEach((_, index) => {
    const dot = document.createElement('button');
    dot.className = `hero-dot ${index === currentSlide ? 'active' : ''}`;
    dot.setAttribute('aria-label', `Go to slide ${index + 1}`);
    dot.addEventListener('click', () => {
      currentSlide = index;
      updateHeroSlide();
      resetHeroAutoPlay();
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

function prevHeroSlide() {
  currentSlide = (currentSlide - 1 + slides.length) % slides.length;
  updateHeroSlide();
}

function startHeroAutoPlay() {
  stopHeroAutoPlay();
  heroAutoPlayInterval = setInterval(nextHeroSlide, 6000);
}

function stopHeroAutoPlay() {
  if (heroAutoPlayInterval) {
    clearInterval(heroAutoPlayInterval);
    heroAutoPlayInterval = null;
  }
}

function resetHeroAutoPlay() {
  stopHeroAutoPlay();
  startHeroAutoPlay();
}

if (slides.length > 0) {
  renderHeroDots();
  startHeroAutoPlay();
}

// ========== HERO SWIPE - TOUCH (Mobile) ==========
let heroTouchStartX = 0;
let heroTouchStartY = 0;

if (heroSection) {
  heroSection.addEventListener('touchstart', (e) => {
    heroTouchStartX = e.changedTouches[0].screenX;
    heroTouchStartY = e.changedTouches[0].screenY;
  }, { passive: true });

  heroSection.addEventListener('touchend', (e) => {
    const heroTouchEndX = e.changedTouches[0].screenX;
    const heroTouchEndY = e.changedTouches[0].screenY;
    const deltaX = heroTouchStartX - heroTouchEndX;
    const deltaY = Math.abs(heroTouchStartY - heroTouchEndY);

    if (Math.abs(deltaX) > 50 && Math.abs(deltaX) > deltaY) {
      stopHeroAutoPlay();
      if (deltaX > 0) {
        nextHeroSlide();
      } else {
        prevHeroSlide();
      }
      setTimeout(startHeroAutoPlay, 6000);
    }
  }, { passive: true });
}

// ========== HERO SWIPE - MOUSE DRAG (Desktop) ==========
let heroMouseStartX = 0;
let heroIsDragging = false;
let heroMoved = false;

if (heroSection) {
  heroSection.addEventListener('mousedown', (e) => {
    if (e.target.closest('.btn') || e.target.closest('.hero-dot')) return;
    heroIsDragging = true;
    heroMoved = false;
    heroMouseStartX = e.clientX;
    heroSection.style.cursor = 'grabbing';
  });

  document.addEventListener('mousemove', (e) => {
    if (!heroIsDragging) return;
    if (Math.abs(e.clientX - heroMouseStartX) > 5) {
      heroMoved = true;
    }
  });

  document.addEventListener('mouseup', (e) => {
    if (!heroIsDragging) return;
    heroIsDragging = false;
    heroSection.style.cursor = '';
    
    if (heroMoved) {
      const diff = heroMouseStartX - e.clientX;
      if (Math.abs(diff) > 50) {
        stopHeroAutoPlay();
        if (diff > 0) nextHeroSlide();
        else prevHeroSlide();
        setTimeout(startHeroAutoPlay, 6000);
      }
    }
  });
}

// ========== HERO SWIPE - TRACKPAD 2-FINGER SWIPE (wheel event) ==========
let heroWheelTimeout = null;
let heroWheelDelta = 0;

if (heroSection) {
  heroSection.addEventListener('wheel', (e) => {
    // Only respond to horizontal trackpad swipes
    if (Math.abs(e.deltaX) > Math.abs(e.deltaY) && Math.abs(e.deltaX) > 10) {
      e.preventDefault();
      
      heroWheelDelta += e.deltaX;
      
      clearTimeout(heroWheelTimeout);
      heroWheelTimeout = setTimeout(() => {
        if (Math.abs(heroWheelDelta) > 50) {
          stopHeroAutoPlay();
          if (heroWheelDelta > 0) nextHeroSlide();
          else prevHeroSlide();
          setTimeout(startHeroAutoPlay, 6000);
        }
        heroWheelDelta = 0;
      }, 50);
    }
  }, { passive: false });
}

// ========== CATEGORIES ==========
const categoriesGrid = document.getElementById('categoriesGrid');
function renderCategories() {
  if (!categoriesGrid) return;
  categoriesGrid.innerHTML = '';
  categories.forEach(cat => {
    const card = document.createElement('div');
    card.className = 'category-card';
    card.innerHTML = `
      <div class="category-image" style="background-image:url('${cat.image}')">
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

  if (bestsellersPrev) bestsellersPrev.disabled = bestsellerIndex === 0;
  const maxIndex = Math.max(0, bestsellersTrack.children.length - itemsPerView);
  if (bestsellersNext) bestsellersNext.disabled = bestsellerIndex >= maxIndex;
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

// ========== BESTSELLERS SWIPE - TOUCH ==========
let bsTouchStartX = 0;
let bsTouchStartY = 0;

if (bestsellersTrack) {
  bestsellersTrack.addEventListener('touchstart', (e) => {
    bsTouchStartX = e.touches[0].clientX;
    bsTouchStartY = e.touches[0].clientY;
  }, { passive: true });

  bestsellersTrack.addEventListener('touchend', (e) => {
    const endX = e.changedTouches[0].clientX;
    const endY = e.changedTouches[0].clientY;
    const deltaX = bsTouchStartX - endX;
    const deltaY = Math.abs(bsTouchStartY - endY);
    const maxIndex = Math.max(0, bestsellersTrack.children.length - itemsPerView);

    if (Math.abs(deltaX) > 50 && Math.abs(deltaX) > deltaY) {
      if (deltaX > 0 && bestsellerIndex < maxIndex) {
        bestsellerIndex++;
        updateBestsellersCarousel();
      } else if (deltaX < 0 && bestsellerIndex > 0) {
        bestsellerIndex--;
        updateBestsellersCarousel();
      }
    }
  }, { passive: true });
}

// ========== BESTSELLERS SWIPE - MOUSE DRAG ==========
let bsMouseStartX = 0;
let bsIsDragging = false;
let bsMoved = false;

if (bestsellersTrack) {
  bestsellersTrack.addEventListener('mousedown', (e) => {
    if (e.target.closest('.wishlist-btn') || e.target.closest('.view-details')) return;
    bsIsDragging = true;
    bsMoved = false;
    bsMouseStartX = e.clientX;
    bestsellersTrack.style.cursor = 'grabbing';
  });

  document.addEventListener('mousemove', (e) => {
    if (!bsIsDragging) return;
    if (Math.abs(e.clientX - bsMouseStartX) > 5) bsMoved = true;
  });

  document.addEventListener('mouseup', (e) => {
    if (!bsIsDragging) return;
    bsIsDragging = false;
    bestsellersTrack.style.cursor = '';
    
    if (bsMoved) {
      const diff = bsMouseStartX - e.clientX;
      const maxIndex = Math.max(0, bestsellersTrack.children.length - itemsPerView);
      if (diff > 50 && bestsellerIndex < maxIndex) {
        bestsellerIndex++;
        updateBestsellersCarousel();
      } else if (diff < -50 && bestsellerIndex > 0) {
        bestsellerIndex--;
        updateBestsellersCarousel();
      }
    }
  });
}

// ========== BESTSELLERS SWIPE - TRACKPAD 2-FINGER ==========
let bsWheelTimeout = null;
let bsWheelDelta = 0;

if (bestsellersTrack) {
  bestsellersTrack.addEventListener('wheel', (e) => {
    if (Math.abs(e.deltaX) > Math.abs(e.deltaY) && Math.abs(e.deltaX) > 10) {
      e.preventDefault();
      
      bsWheelDelta += e.deltaX;
      
      clearTimeout(bsWheelTimeout);
      bsWheelTimeout = setTimeout(() => {
        const maxIndex = Math.max(0, bestsellersTrack.children.length - itemsPerView);
        if (bsWheelDelta > 50 && bestsellerIndex < maxIndex) {
          bestsellerIndex++;
          updateBestsellersCarousel();
        } else if (bsWheelDelta < -50 && bestsellerIndex > 0) {
          bestsellerIndex--;
          updateBestsellersCarousel();
        }
        bsWheelDelta = 0;
      }, 50);
    }
  }, { passive: false });
}

// ========== INITIALIZE ==========
document.addEventListener('DOMContentLoaded', () => {
  renderCategories();
  
  document.querySelectorAll('.carousel-item').forEach(item => {
    let clickTime = 0;
    let clickX = 0;
    
    item.addEventListener('mousedown', (e) => {
      clickTime = Date.now();
      clickX = e.clientX;
    });
    
    item.addEventListener('click', (e) => {
      const duration = Date.now() - clickTime;
      const distance = Math.abs(e.clientX - clickX);
      
      if (duration < 300 && distance < 10) {
        if (!e.target.closest('.wishlist-btn') && !e.target.closest('.view-details')) {
          gotoProduct(item.dataset.productId, item.dataset.variantId, item.dataset.variantSku);
        }
      }
    });

    const wishlistBtn = item.querySelector('.wishlist-btn');
    if (wishlistBtn) {
      checkWishlistStatus(wishlistBtn.dataset.variantId, wishlistBtn);
      wishlistBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleWishlist(wishlistBtn.dataset.variantId, wishlistBtn.dataset.productId, wishlistBtn);
      });
    }

    const viewBtn = item.querySelector('.view-details');
    if (viewBtn) {
      viewBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        gotoProduct(item.dataset.productId, item.dataset.variantId, item.dataset.variantSku);
      });
    }
  });

  updateItemsPerView();
  updateBestsellersCarousel();
});

window.addEventListener('resize', updateBestsellersCarousel);

// ========== TAG SECTIONS ==========
function loadTagSections() {
  fetch('/ajax/tag_sections')
    .then(response => response.json())
    .then(data => {
      const container = document.getElementById('tagSectionsContainer');
      if (!container) return;
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
                        <div class="tag-price">₹${variant.price || '0.00'}</div>
                      </div>
                    </div>
                  `).join('')}
                </div>
                <button class="tag-nav next" data-section="${sectionIdx}">›</button>
              </div>
            </div>
          `;
          container.appendChild(sectionEl);

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
            track.style.transform = `translateX(-${tagIndex * itemWidth}px)`;
            prevBtn.disabled = tagIndex === 0;
            nextBtn.disabled = tagIndex >= Math.max(0, track.children.length - itemsPerTagView);
          }

          prevBtn.addEventListener('click', () => {
            if (tagIndex > 0) {
              tagIndex--;
              updateTagCarousel();
            }
          });

          nextBtn.addEventListener('click', () => {
            if (tagIndex < Math.max(0, track.children.length - itemsPerTagView)) {
              tagIndex++;
              updateTagCarousel();
            }
          });

          // Touch swipe
          let tagTouchStartX = 0;
          let tagTouchStartY = 0;
          track.addEventListener('touchstart', (e) => {
            tagTouchStartX = e.touches[0].clientX;
            tagTouchStartY = e.touches[0].clientY;
          }, { passive: true });
          track.addEventListener('touchend', (e) => {
            const endX = e.changedTouches[0].clientX;
            const endY = e.changedTouches[0].clientY;
            const deltaX = tagTouchStartX - endX;
            const deltaY = Math.abs(tagTouchStartY - endY);
            const maxIndex = Math.max(0, track.children.length - itemsPerTagView);
            if (Math.abs(deltaX) > 50 && Math.abs(deltaX) > deltaY) {
              if (deltaX > 0 && tagIndex < maxIndex) {
                tagIndex++;
                updateTagCarousel();
              } else if (deltaX < 0 && tagIndex > 0) {
                tagIndex--;
                updateTagCarousel();
              }
            }
          }, { passive: true });

          // Mouse drag
          // ========== HERO SWIPE - MOUSE DRAG (Desktop) ==========
let heroMouseStartX = 0;
let heroIsDragging = false;
let heroMoved = false;

if (heroSection) {
  heroSection.addEventListener('mousedown', (e) => {
    // Check if clicking on a button or link
    const clickedButton = e.target.closest('.btn');
    const clickedDot = e.target.closest('.hero-dot');
    
    if (clickedButton || clickedDot) {
      // Don't start drag, let the click through
      return;
    }
    
    heroIsDragging = true;
    heroMoved = false;
    heroMouseStartX = e.clientX;
    heroSection.style.cursor = 'grabbing';
    e.preventDefault(); // Only prevent default if NOT clicking button
  });

  document.addEventListener('mousemove', (e) => {
    if (!heroIsDragging) return;
    if (Math.abs(e.clientX - heroMouseStartX) > 5) {
      heroMoved = true;
    }
  });

  document.addEventListener('mouseup', (e) => {
    if (!heroIsDragging) return;
    heroIsDragging = false;
    heroSection.style.cursor = '';
    
    if (heroMoved) {
      const diff = heroMouseStartX - e.clientX;
      if (Math.abs(diff) > 50) {
        stopHeroAutoPlay();
        if (diff > 0) nextHeroSlide();
        else prevHeroSlide();
        setTimeout(startHeroAutoPlay, 6000);
      }
    }
  });
}

          // Trackpad 2-finger swipe
          let tagWheelTimeout = null;
          let tagWheelDelta = 0;
          track.addEventListener('wheel', (e) => {
            if (Math.abs(e.deltaX) > Math.abs(e.deltaY) && Math.abs(e.deltaX) > 10) {
              e.preventDefault();
              tagWheelDelta += e.deltaX;
              clearTimeout(tagWheelTimeout);
              tagWheelTimeout = setTimeout(() => {
                const maxIndex = Math.max(0, track.children.length - itemsPerTagView);
                if (tagWheelDelta > 50 && tagIndex < maxIndex) {
                  tagIndex++;
                  updateTagCarousel();
                } else if (tagWheelDelta < -50 && tagIndex > 0) {
                  tagIndex--;
                  updateTagCarousel();
                }
                tagWheelDelta = 0;
              }, 50);
            }
          }, { passive: false });

          sectionEl.querySelectorAll('.tag-item').forEach(item => {
            let clickTime = 0;
            let clickX = 0;
            item.addEventListener('mousedown', (e) => {
              clickTime = Date.now();
              clickX = e.clientX;
            });
            item.addEventListener('click', (e) => {
              if (Date.now() - clickTime < 300 && Math.abs(e.clientX - clickX) < 10) {
                if (!e.target.closest('.wishlist-btn')) {
                  gotoProduct(item.dataset.productId, item.dataset.variantId, item.dataset.variantSku);
                }
              }
            });
            const wishlistBtn = item.querySelector('.wishlist-btn');
            if (wishlistBtn) {
              checkWishlistStatus(wishlistBtn.dataset.variantId, wishlistBtn);
              wishlistBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                toggleWishlist(wishlistBtn.dataset.variantId, wishlistBtn.dataset.productId, wishlistBtn);
              });
            }
          });

          updateTagCarousel();
          window.addEventListener('resize', updateTagCarousel);
        });
      }
    })
    .catch(error => console.error('Error loading tag sections:', error));
}

document.addEventListener('DOMContentLoaded', loadTagSections);

// ========== TESTIMONIALS ==========
let currentTestimonial = 0;
const testimonialText = document.getElementById('testimonialText');
const testimonialAuthor = document.getElementById('testimonialAuthor');
const prevTestimonialBtn = document.getElementById('prevTestimonial');
const nextTestimonialBtn = document.getElementById('nextTestimonial');

function updateTestimonial() {
  if (!testimonialText || !testimonialAuthor) return;
  const testimonial = testimonials[currentTestimonial];
  testimonialText.textContent = testimonial.text;
  testimonialAuthor.textContent = `— ${testimonial.name}`;
}

if (prevTestimonialBtn && nextTestimonialBtn) {
  prevTestimonialBtn.addEventListener('click', () => {
    currentTestimonial = (currentTestimonial - 1 + testimonials.length) % testimonials.length;
    updateTestimonial();
  });
  nextTestimonialBtn.addEventListener('click', () => {
    currentTestimonial = (currentTestimonial + 1) % testimonials.length;
    updateTestimonial();
  });
}

document.addEventListener('DOMContentLoaded', updateTestimonial);