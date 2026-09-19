import { Moon, Sun } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { useTheme } from '@/context/theme-context';

// 精简版明暗切换（上游 theme-switch.tsx 的模式保留，色板/字体子菜单裁掉——本项目单一守岸人色板）。
export function ThemeSwitch() {
  const { resolved, setTheme } = useTheme();
  const { t } = useTranslation();

  return (
    <Button
      variant='ghost'
      size='icon'
      className='rounded-full'
      aria-label={resolved === 'dark' ? t('theme.toLight') : t('theme.toDark')}
      onClick={() => setTheme(resolved === 'dark' ? 'light' : 'dark')}
    >
      <Sun className='size-5 scale-100 rotate-0 transition-all dark:scale-0 dark:-rotate-90' />
      <Moon className='absolute size-5 scale-0 rotate-90 transition-all dark:scale-100 dark:rotate-0' />
    </Button>
  );
}
