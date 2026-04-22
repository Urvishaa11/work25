const menuButton = document.querySelector('.mobile-menu-button');
const mobileMenu = document.querySelector('.mobile-menu');

if (menuButton && mobileMenu) {
  menuButton.addEventListener('click', () => mobileMenu.classList.toggle('hidden'));
}

document.querySelectorAll('.validated-form').forEach((form) => {
  form.addEventListener('submit', (event) => {
    clearErrors(form);
    let valid = true;
    form.querySelectorAll('[required]').forEach((field) => {
      const value = field.value.trim();
      if (!value) {
        valid = false;
        showError(field, 'This field is required.');
      }
      if (field.dataset.validate === 'mobile' && value) {
        if (!/^[6-9]\d{9}$/.test(value)) {
          valid = false;
          showError(field, 'Enter a valid 10-digit mobile number.');
        }
      }
    });
    if (!valid) event.preventDefault();
  });
});

function clearErrors(form) {
  form.querySelectorAll('.field-error').forEach((item) => item.remove());
  form.querySelectorAll('.is-invalid').forEach((item) => item.classList.remove('is-invalid'));
}

function showError(field, message) {
  field.classList.add('is-invalid');
  const error = document.createElement('div');
  error.className = 'field-error';
  error.textContent = message;
  field.insertAdjacentElement('afterend', error);
}

const portalRoleButtons = document.querySelectorAll('.portal-role-btn');
const portalTabButtons = document.querySelectorAll('.portal-tab-btn');
const portalTabPanels = document.querySelectorAll('.portal-tab-panel');
const portalRoleLabels = document.querySelectorAll('.portal-role-label');
const loginRoleInput = document.getElementById('loginRoleInput');
const workerRegisterForm = document.getElementById('worker-register-form');
const sellerRegisterForm = document.getElementById('seller-register-form');

if (portalRoleButtons.length) {
  portalRoleButtons.forEach((button) => {
    button.addEventListener('click', () => setPortalRole(button.dataset.roleTarget));
  });
}

if (portalTabButtons.length) {
  portalTabButtons.forEach((button) => {
    button.addEventListener('click', () => {
      portalTabButtons.forEach((item) => {
        item.classList.remove('active-chip');
        item.classList.add('filter-chip');
      });
      button.classList.remove('filter-chip');
      button.classList.add('active-chip');
      portalTabPanels.forEach((panel) => panel.classList.add('hidden'));
      const target = document.getElementById(button.dataset.tabTarget);
      if (target) target.classList.remove('hidden');
    });
  });
}

function setPortalRole(role) {
  portalRoleButtons.forEach((button) => {
    button.classList.remove('active-chip');
    button.classList.add('filter-chip');
    if (button.dataset.roleTarget === role) {
      button.classList.remove('filter-chip');
      button.classList.add('active-chip');
    }
  });

  portalRoleLabels.forEach((label) => {
    label.textContent = role === 'seller' ? 'Seller' : 'Worker';
  });

  if (loginRoleInput) loginRoleInput.value = role;
  if (workerRegisterForm) workerRegisterForm.classList.toggle('hidden', role !== 'worker');
  if (sellerRegisterForm) sellerRegisterForm.classList.toggle('hidden', role !== 'seller');
}
