import type { ButtonHTMLAttributes, ReactNode } from 'react';

type ButtonVariant = 'icon' | 'control' | 'primary' | 'primary2nd' | 'secondary';

interface ButtonCommonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  isActive?: boolean;
}

type ButtonSize =
  | 'small'
  | 'large'
  | 'simple'
  ;

interface ButtonCommonProps
  extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  isActive?: boolean;
  icon?: ReactNode;
}

const sizeClasses: Record<ButtonSize, string> = {
  small: '',
  
  large:
    'font-inter min-h-8 px-4 rounded-full text-[13.5px] gap-3 [&:hover:not(:disabled)]:opacity-[0.8]',

  simple: 
    'font-inter min-h-8 px-4 rounded-full bg:text-white text-[#393939] text-[13.5px] gap-3 [&:hover:not(:disabled)]:opacity-[0.8]'
};

const baseClasses =
  'cursor-pointer inline-flex items-center justify-center [transition:filter_0.1s_ease,background_0.1s_ease] disabled:opacity-50 disabled:cursor-not-allowed';

const variantClasses: Record<ButtonVariant, string> = {
  icon: 'w-8 h-8 rounded-lg border border-[#e2e5ea] bg-white text-sm text-[#1f2430] [&:hover:not(:disabled)]:bg-[#f1f2f4]',
  control:
    'w-16 h-16 rounded-full bg-[#2f6fe4] text-white text-xs font-light flex-shrink-0 [&:hover:not(:disabled)]:brightness-[0.92]',
  primary:
    'font-inter py-1.5 px-3 rounded-2xl text-[13px] font-light cursor-pointer bg-[#393939] text-white [&:hover:bg-sky-700 dark:border dark:border-[#6D6D6D] dark:bg-[#2D2D2D]',
  primary2nd:
    'font-inter py-1.5 px-3 rounded-2xl text-[13px] font-light cursor-pointer border border-[#F7F7F7] bg-white text-[#393939] [&:hover:bg-[#393939] dark:text-white dark:bg-[#2D2D2D] dark:border dark:border-[#6D6D6D]',
    secondary:
    'font-inter py-1.5 px-3 rounded-2xl text-[13px] font-light cursor-pointer dark:text-white bg-transparent [&:hover:bg-sky-700',
};

const controlActiveClass = '!bg-[#F9EBEB] !border !border-[#E29F9C] dark:!text-[#393939] dark:!bg-[#D7B2B2] dark:!border-[#BB7B78]';

export function ButtonCommon({
  variant = 'primary',
  size = 'small',
  isActive = false,
  icon,
  children,
  className = '',
  type = 'button',
  ...rest
}: ButtonCommonProps) {
  const activeClass =
    variant === 'primary2nd' && isActive
      ? controlActiveClass
      : '';

  return (
    <button
      type={type}
      className={`
        ${baseClasses}
        ${variantClasses[variant]}
        ${sizeClasses[size]}
        ${activeClass}
        ${className}
      `.trim()}
      {...rest}
    >
      {icon && (
        <span className="shrink-0 flex items-center">
          {icon}
        </span>
      )}

      <span>{children}</span>
    </button>
  );
}
