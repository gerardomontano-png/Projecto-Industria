import { useEffect, useState } from 'react';
import Header, { type AppView } from './components/Header';
import MainPanel from './components/MainPanel/MainPanel';
import { InferencePanel } from './components/InferencePanel/InferencePanel';
import './App.css';

function App() {
  const [view, setView] = useState<AppView>('monitor');

  const [isDarkMode, setIsDarkMode] = useState(false);

  // const toggleTheme = () =>{
  //   const newTheme = isDarkMode == false ? true : false;
  //   setIsDarkMode(newTheme);
  //   document.documentElement.classList.toggle('dark', newTheme == true)
  // }
    
  useEffect(() => {
    document.body.classList.toggle('dark', isDarkMode)
  },[isDarkMode]); 

  return (
    <>
      <Header view={view} onViewChange={setView} isDarkMode={isDarkMode} setIsDarkMode={setIsDarkMode} />
      {view === 'monitor' ? <MainPanel /> : <InferencePanel />}
    </>
  );
}

export default App;
