import { Component } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center py-20 text-center animate-fade-in">
          <div className="w-14 h-14 rounded-2xl bg-danger-light flex items-center justify-center mb-4">
            <AlertTriangle size={24} className="text-danger" />
          </div>
          <h3 className="text-sm font-semibold text-text mb-1">Произошла ошибка</h3>
          <p className="text-sm text-text-secondary max-w-sm mb-4">
            {this.props.fallbackMessage || 'Что-то пошло не так при загрузке этого раздела.'}
          </p>
          <button
            onClick={this.handleRetry}
            className="flex items-center gap-2 px-4 py-2 text-sm font-medium bg-primary text-white rounded-xl hover:bg-primary-dark transition-colors"
          >
            <RefreshCw size={14} />
            Попробовать снова
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
