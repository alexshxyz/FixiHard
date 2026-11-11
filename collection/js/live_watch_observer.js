
        ([callbackName, observerKey]) => {
            const liveTable = document.querySelector('#table_live');
            if (!liveTable) {
                throw new Error('#table_live not found.');
            }
            const belongsToLiveTable = (node) => {
                const element = node.nodeType === Node.ELEMENT_NODE
                    ? node
                    : node.parentElement;
                return Boolean(
                    element && element.closest('table#table_live')
                );
            };
            const containsLiveTable = (node) => {
                const element = node.nodeType === Node.ELEMENT_NODE
                    ? node
                    : node.parentElement;
                return Boolean(
                    element && (
                        element.matches('table#table_live') ||
                        element.querySelector('table#table_live')
                    )
                );
            };

            const observer = new MutationObserver((records) => {
                const liveTableChanged = records.some((record) => {
                    if (belongsToLiveTable(record.target)) return true;
                    return [...record.addedNodes, ...record.removedNodes].some(
                        (node) => belongsToLiveTable(node) ||
                            containsLiveTable(node)
                    );
                });
                if (liveTableChanged) window[callbackName]();
            });
            observer.observe(document.documentElement, {
                childList: true,
                subtree: true,
                characterData: true,
                attributes: true,
                attributeFilter: ['class', 'style'],
            });
            window[observerKey] = observer;
        }
