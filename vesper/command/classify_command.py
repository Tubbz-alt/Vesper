"""Module containing class `ClassifyCommand`."""


from vesper.command.command import Command, CommandSyntaxError
from vesper.singletons import extension_manager
import vesper.command.command_utils as command_utils


class ClassifyCommand(Command):
    
    
    extension_name = 'classify'
    
    
    def __init__(self, args):
        super().__init__(args)
        name = command_utils.get_required_arg('classifier', args)
        # self._classifier = _create_classifier(name)
        
        
    def execute(self, job_info):
        print('ClassifyCommand.execute')
        return True


def _create_classifier(name):
    cls = _get_classifier_class(name)
    return cls()


def _get_classifier_class(name):
    classes = extension_manager.instance.get_extensions('Classifier')
    try:
        return classes[name]
    except KeyError:
        raise CommandSyntaxError(
            'Unrecognized classifier name "{}".'.format(name))