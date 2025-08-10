'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useUser } from '@/contexts/UserContext';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { 
  User as UserIcon, 
  LogOut, 
  Settings, 
  Shield, 
  Stethoscope,
  Heart,
  Users
} from 'lucide-react';
import { useTranslations } from 'next-intl';

const getRoleIcon = (role: string) => {
  switch (role.toLowerCase()) {
    case 'doctor':
      return <Stethoscope className="h-4 w-4" />;
    case 'nurse':
      return <Heart className="h-4 w-4" />;
    case 'admin':
      return <Shield className="h-4 w-4" />;
    default:
      return <Users className="h-4 w-4" />;
  }
};

const getRoleBadgeVariant = (role: string) => {
  switch (role.toLowerCase()) {
    case 'doctor':
      return 'default' as const;
    case 'nurse':
      return 'secondary' as const;
    case 'admin':
      return 'destructive' as const;
    default:
      return 'outline' as const;
  }
};

export function UserProfile() {
  const t = useTranslations();
  const router = useRouter();
  const { user, logout } = useUser();
  const [isLoggingOut, setIsLoggingOut] = useState(false);

  const handleProfileClick = () => {
    console.log('Profile clicked - navigating to /profile');
    router.push('/profile');
  };

  const handleSettingsClick = () => {
    console.log('Settings clicked - navigating to /settings');
    router.push('/settings');
  };

  if (!user) return null;

  const handleLogout = async () => {
    setIsLoggingOut(true);
    try {
      await logout();
    } catch (err) {
      console.error('Logout failed:', err);
    } finally {
      setIsLoggingOut(false);
    }
  };

  const initials = `${user.first_name?.[0] || ''}${user.last_name?.[0] || ''}` || user.username[0].toUpperCase();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" className="relative h-10 w-10 rounded-full">
          <Avatar className="h-10 w-10">
            <AvatarFallback className="bg-blue-100 text-blue-600">
              {initials}
            </AvatarFallback>
          </Avatar>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-80" align="end" forceMount>
        <DropdownMenuLabel className="font-normal">
          <div className="flex flex-col space-y-2">
            <div className="flex items-center space-x-2">
              <Avatar className="h-8 w-8">
                <AvatarFallback className="bg-blue-100 text-blue-600 text-sm">
                  {initials}
                </AvatarFallback>
              </Avatar>
              <div className="flex-1">
                <p className="text-sm font-medium leading-none">{user.display_name}</p>
                <p className="text-xs leading-none text-muted-foreground mt-1">
                  @{user.username}
                </p>
              </div>
            </div>
            
            <div className="flex items-center justify-between">
              <Badge variant={getRoleBadgeVariant(user.role)} className="text-xs">
                <span className="mr-1">{getRoleIcon(user.role)}</span>
                {user.role.charAt(0).toUpperCase() + user.role.slice(1)}
              </Badge>
              {user.department && (
                <span className="text-xs text-muted-foreground">
                  {user.department}
                </span>
              )}
            </div>
            
            <div className="text-xs text-muted-foreground">
              <p>{user.email}</p>
            </div>
          </div>
        </DropdownMenuLabel>
        
        <DropdownMenuSeparator />
        
        <DropdownMenuItem 
          className="cursor-pointer"
          onClick={handleProfileClick}
        >
          <UserIcon className="mr-2 h-4 w-4" />
          <span>{t('common.profile')}</span>
        </DropdownMenuItem>
        
        <DropdownMenuItem 
          className="cursor-pointer"
          onClick={handleSettingsClick}
        >
          <Settings className="mr-2 h-4 w-4" />
          <span>{t('common.settings')}</span>
        </DropdownMenuItem>
        
        <DropdownMenuSeparator />
        
        <DropdownMenuItem 
          className="cursor-pointer text-red-600 focus:text-red-600"
          onClick={handleLogout}
          disabled={isLoggingOut}
        >
          <LogOut className="mr-2 h-4 w-4" />
          <span>{isLoggingOut ? t('common.signingOut') : t('common.signOut')}</span>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}